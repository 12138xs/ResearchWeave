from __future__ import annotations

import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from apps.papers.deep_parser import (
    DEEP_SECTION_SPECS,
    DeepParserInput,
    DeepParseResult,
    LocalPdfDeepParserProvider,
    _build_llm_summary,
    _build_llm_messages,
    _clean_section_markdown,
    get_deep_parser_provider,
)
from apps.papers.deep_processing import _validate_deep_parse_result
from apps.papers.models import Paper
from apps.papers.tasks import run_paper_deep_process_task
from apps.tasks.models import TaskRecord


class DeepParserMarkdownNormalizationTests(SimpleTestCase):
    def _fake_pdf_reader(self, text: str):
        class FakePage:
            def extract_text(self) -> str:
                return text

        class FakeReader:
            def __init__(self, path: str) -> None:
                self.path = path
                self.pages = [FakePage()]

        return FakeReader

    def _parse_input_with_storage_pdf(
        self,
        parser_input: DeepParserInput,
        *,
        pdf_text: str,
    ) -> DeepParseResult:
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / parser_input.source_pdf_path
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(b"%PDF-1.4\n% test pdf")
            with override_settings(STORAGE_ROOT=Path(tmpdir)), patch(
                "apps.papers.deep_parser.PdfReader",
                self._fake_pdf_reader(pdf_text),
            ):
                return LocalPdfDeepParserProvider().parse(parser_input)

    def test_clean_section_markdown_wraps_bare_tex_commands(self) -> None:
        markdown = (
            "Method residual uses \\partial_u f_\\theta(x,t), "
            "\\mathcal{L}_pde, \\theta, and \\frac{u_t}{u_x} without delimiters."
        )

        cleaned = _clean_section_markdown(markdown, title="Method")

        self.assertIn("$\\partial_u f_\\theta(x,t)$", cleaned)
        self.assertIn("$\\mathcal{L}_pde$", cleaned)
        self.assertIn("$\\theta$", cleaned)
        self.assertIn("$\\frac{u_t}{u_x}$", cleaned)
        without_math = re.sub(r"\$[^$\n]+\$", " ", cleaned)
        self.assertNotRegex(without_math, r"\\(?:partial|mathcal|frac|nabla|theta)\b")

    def test_clean_section_markdown_removes_english_chain_of_thought_leakage(self) -> None:
        markdown = (
            "Now, I need to ensure the section follows the requested structure and does not repeat itself.\n\n"
            "### 原文直译式要点\n"
            "1. 论文围绕 PDE 约束建模展开，仍需回到原文核对公式与实验设置。"
        )

        cleaned = _clean_section_markdown(markdown, title="Method")

        self.assertNotIn("Now, I need to ensure", cleaned)
        self.assertIn("论文围绕 PDE 约束建模展开", cleaned)

    def test_clean_section_markdown_removes_followup_reasoning_leakage(self) -> None:
        markdown = (
            "Now I need to ensure the section follows the requested structure.\n\n"
            "In the section, I have three paragraphs but need to rewrite them.\n\n"
            "In the \"introduction\" section, I have three paragraphs and should rewrite them.\n\n"
            "The instruction says each section should contain substantial Chinese paragraphs.\n\n"
            "### 原文直译式要点\n"
            "1. 论文围绕 PDE 约束建模展开，仍需回到原文核对公式与实验设置。"
        )

        cleaned = _clean_section_markdown(markdown, title="Method")

        self.assertNotIn("Now I need", cleaned)
        self.assertNotIn("In the section", cleaned)
        self.assertNotIn("In the \"introduction\" section", cleaned)
        self.assertNotIn("The instruction says", cleaned)
        self.assertIn("论文围绕 PDE 约束建模展开", cleaned)

    def test_clean_section_markdown_wraps_bare_formula_fragments_without_touching_protected_blocks(self) -> None:
        markdown = (
            "Tokens F_\\theta and t^n define the state, while I_i=[x_i,x_{i+1}] names an interval.\n"
            "The long residual F_\\theta(t^n, I_i=[x_i,x_{i+1}]) = \\int_0^1 u dx + \\sum_i r_i + \\partial_t u "
            "should render as math.\n\n"
            "```python\n"
            "loss = F_\\theta + t^n\n"
            "```\n"
            "Existing inline $F_\\theta$ and display $$\\sum_i r_i$$ should stay untouched."
        )

        cleaned = _clean_section_markdown(markdown, title="Method")

        self.assertIn("$F_\\theta$", cleaned)
        self.assertIn("$t^n$", cleaned)
        self.assertIn("$I_i=[x_i,x_{i+1}]$", cleaned)
        self.assertIn("$F_\\theta(t^n, I_i=[x_i,x_{i+1}]) = \\int_0^1 u dx + \\sum_i r_i + \\partial_t u$", cleaned)
        self.assertIn("```python\nloss = F_\\theta + t^n\n```", cleaned)
        self.assertIn("`loss = F_\\theta + t^n`", _clean_section_markdown("Inline code `loss = F_\\theta + t^n` stays code.", title="Method"))
        self.assertEqual(cleaned.count("$F_\\theta$"), 2)
        self.assertIn("$$\\sum_i r_i$$", cleaned)
        without_code = re.sub(r"```.*?```", " ", cleaned, flags=re.DOTALL)
        without_display_math = re.sub(r"\$\$.*?\$\$", " ", without_code, flags=re.DOTALL)
        without_inline_math = re.sub(r"\$[^$\n]+\$", " ", without_display_math)
        self.assertNotRegex(without_inline_math, r"(?:F_\\theta|t\^n|I_i=\[|\\(?:mathcal|frac|int|sum|partial)\b)")

    def test_llm_summary_is_short_intro_not_repeated_section_digests(self) -> None:
        parser_input = DeepParserInput(
            paper_id=1,
            title="Compact Summary Contract",
            abstract="A paper about PDE methods.",
            source_pdf_path="quarantine/uploads/summary.pdf",
        )
        sections = [
            {
                "title": spec["title"],
                "summary": f"{spec['title']} 这一节包含一段很长的章节摘要，页面主体已经会单独展示，不应该复制到顶部摘要。"
            }
            for spec in DEEP_SECTION_SPECS
        ]

        summary = _build_llm_summary(parser_input, sections)

        self.assertIn("Compact Summary Contract", summary)
        self.assertLess(len(summary), 180)
        for spec in DEEP_SECTION_SPECS:
            self.assertNotIn(f"- {spec['title']}", summary)
        self.assertNotIn("这一节包含一段很长的章节摘要", summary)

    def test_llm_prompt_locks_deep_reading_template_and_internal_subsections(self) -> None:
        parser_input = DeepParserInput(
            paper_id=1,
            title="Template Contract",
            abstract="A paper about PDE methods.",
            source_pdf_path="quarantine/uploads/template.pdf",
            guidance="重点关注方法公式和复现实验",
        )

        messages = _build_llm_messages(
            parser_input=parser_input,
            pages=[{"page": 1, "text": "Abstract\nMethod\nResults\nConclusion"}],
            full_text="Abstract\nMethod\nResults\nConclusion",
        )

        system_prompt = messages[0]["content"]
        self.assertIn("Use the following four level-2 headings exactly and no other level-2 headings", system_prompt)
        self.assertIn("## 引言与研究背景\n## 方法介绍\n## 核心结果与结论\n## 总结", system_prompt)
        self.assertIn("原文直译式要点", system_prompt)
        self.assertIn("梳理与扩展", system_prompt)
        self.assertIn("核对建议", system_prompt)
        self.assertIn("算法/流程草图", system_prompt)
        self.assertIn("Do not include chain-of-thought", system_prompt)
        self.assertIn("Do not paste long English source paragraphs", system_prompt)
        self.assertIn("If a user reading guidance is provided", system_prompt)
        self.assertIn("necessary English terms, paper titles, variable names", system_prompt)
        self.assertNotIn("Formalization", system_prompt)
        self.assertIn("User reading guidance: 重点关注方法公式和复现实验", messages[1]["content"])

    @override_settings(PAPER_DEEP_LLM_TIMEOUT_SECONDS=180)
    @patch("apps.papers.deep_parser.call_minimax_chat", create=True)
    def test_provider_passes_deep_llm_timeout_to_minimax(self, mocked_chat) -> None:
        mocked_chat.return_value = "\n\n".join(
            f"## {spec['title']}\n原文直译式要点、梳理与扩展、核对建议都需要人工核对。"
            for spec in DEEP_SECTION_SPECS
        )
        parser_input = DeepParserInput(
            paper_id=1,
            title="Timeout Contract",
            abstract="A timeout regression paper.",
            source_pdf_path="quarantine/uploads/timeout.pdf",
        )

        self._parse_input_with_storage_pdf(
            parser_input,
            pdf_text="Abstract\nA timeout regression.\nMethods\nThe loss uses u_t + u_x = 0.\n",
        )

        self.assertEqual(mocked_chat.call_args.kwargs["timeout"], 180)

    @patch("apps.papers.deep_parser.call_minimax_chat", create=True)
    def test_provider_wraps_llm_tex_commands_in_markdown_math(self, mocked_chat) -> None:
        headings = [str(spec["title"]) for spec in DEEP_SECTION_SPECS]
        mocked_chat.return_value = f"""
## {headings[0]}
The paper targets PDE forecasting and keeps evidence tied to extracted text.

## {headings[1]}
The method optimizes residual \\partial_u f_\\theta(x,t) and the energy term \\mathcal{{L}}_pde during training.
It also compares the normalized residual with \\frac{{u_t}}{{u_x}} when discussing constraints.

## {headings[2]}
The results section reports qualitative stability and requires manual checking.

## {headings[3]}
The final section separates author claims from reproduction risks.
""".strip()
        parser_input = DeepParserInput(
            paper_id=1,
            title="Bare TeX PDE Parser Regression",
            abstract="A parser regression paper.",
            source_pdf_path="quarantine/uploads/tex.pdf",
        )
        pdf_text = (
            "Abstract\nA PDE parser regression.\n"
            "Methods\n\\partial_u f_\\theta(x,t) = \\mathcal{L}_pde + \\frac{u_t}{u_x}\n"
        )

        result = self._parse_input_with_storage_pdf(parser_input, pdf_text=pdf_text)

        method_summary = str(result.sections[1].get("summary", ""))
        self.assertIn("$\\partial_u f_\\theta(x,t)$", method_summary)
        self.assertIn("$\\mathcal{L}_pde$", method_summary)
        self.assertIn("$\\frac{u_t}{u_x}$", method_summary)
        without_code = re.sub(r"```.*?```", " ", method_summary, flags=re.DOTALL)
        without_math = re.sub(r"\$[^$\n]+\$", " ", without_code)
        self.assertNotRegex(without_math, r"\\(?:partial|mathcal|frac|nabla)\b")
        self.assertTrue(any("\\partial_u" in item.get("text", "") for item in result.formulas))

    def test_safe_latex_keeps_unicode_math_formula_lines(self) -> None:
        from apps.papers.deep_parser import _safe_latex

        self.assertEqual(
            _safe_latex("𝜕𝑡𝐐 + 𝜕𝑥𝐅 (𝐐) + 𝜕𝑦𝐆 (𝐐) = 𝟎, (1)"),
            "𝜕𝑡𝐐 + 𝜕𝑥𝐅 (𝐐) + 𝜕𝑦𝐆 (𝐐) = 𝟎, (1)",
        )
        self.assertEqual(_safe_latex("∂t + ∇ · (vψ) = 0"), "∂t + ∇ · (vψ) = 0")


class DeepParseResultSchemaValidationTests(SimpleTestCase):
    def _valid_result(
        self,
        *,
        summary: str = "合规的中文深度解析摘要。",
        sections: list[dict[str, object]] | None = None,
        figures: list[dict[str, object]] | None = None,
        formulas: list[dict[str, object]] | None = None,
        code_suggestions: list[dict[str, object]] | None = None,
    ) -> DeepParseResult:
        return DeepParseResult(
            parser_name="stub_parser_v1",
            summary=summary,
            sections=sections
            if sections is not None
            else [
                {"index": 1, "title": "引言与研究背景", "summary": "背景摘要。", "page_start": 1, "page_end": 2},
                {"index": 2, "title": "方法介绍", "summary": "方法摘要。", "page_start": 3, "page_end": 4},
                {"index": 3, "title": "核心结果与结论", "summary": "结果摘要。", "page_start": 5, "page_end": 6},
                {
                    "index": 4,
                    "title": "总结",
                    "summary": "总结摘要。",
                    "page_start": None,
                    "page_end": None,
                    "quality_score": 91,
                    "quality": {"overall_score": 91, "overall_needs_review": False},
                },
            ],
            figures=figures
            if figures is not None
            else [{"id": "fig-1", "caption": "Overview figure.", "page": 2, "note": "核对图注。"}],
            formulas=formulas
            if formulas is not None
            else [{"id": "eq-1", "latex": "u_t + u_x = 0", "text": "PDE residual", "note": "核对符号。"}],
            code_suggestions=code_suggestions
            if code_suggestions is not None
            else [{"title": "复现实验", "note": "检查数据、指标和随机种子。"}],
            reproduction_notes="复现建议。",
        )

    def test_rejects_sections_missing_summary_or_non_integer_index(self) -> None:
        result = self._valid_result(
            sections=[
                {"index": "1", "title": "引言与研究背景", "summary": "背景摘要。", "page_start": 1, "page_end": 2},
                {"index": 2, "title": "方法介绍", "page_start": None, "page_end": None},
            ]
        )

        with self.assertRaisesRegex(ValueError, "sections\\[0\\]\\.index must be an integer"):
            _validate_deep_parse_result(result)
        with self.assertRaisesRegex(ValueError, "sections\\[1\\]\\.summary is required"):
            _validate_deep_parse_result(result)

    def test_rejects_nested_items_missing_minimum_keys(self) -> None:
        result = self._valid_result(
            figures=[{"id": "fig-1", "page": 2, "note": "missing caption"}],
            formulas=[{"id": "eq-1", "note": "missing latex and text"}],
            code_suggestions=[{"title": "Missing note"}],
        )

        with self.assertRaisesRegex(ValueError, "figures\\[0\\]\\.caption is required"):
            _validate_deep_parse_result(result)
        with self.assertRaisesRegex(ValueError, "formulas\\[0\\]\\.latex is required"):
            _validate_deep_parse_result(result)
        with self.assertRaisesRegex(ValueError, "formulas\\[0\\]\\.text is required"):
            _validate_deep_parse_result(result)
        with self.assertRaisesRegex(ValueError, "code_suggestions\\[0\\]\\.note is required"):
            _validate_deep_parse_result(result)

    def test_rejects_internal_path_leakage_without_echoing_private_path(self) -> None:
        result = self._valid_result(
            summary="source_pdf_path 指向 quarantine/uploads/private.pdf 的内部调试信息。",
            sections=[
                {
                    "index": 1,
                    "title": "引言与研究背景",
                    "summary": "这里泄露了 source_pdf_path 和 quarantine/uploads/private.pdf。",
                    "page_start": 1,
                    "page_end": 2,
                }
            ],
        )

        with self.assertRaises(ValueError) as context:
            _validate_deep_parse_result(result)

        message = str(context.exception)
        self.assertIn("summary contains internal provider or storage details", message)
        self.assertIn("sections[0].summary contains internal provider or storage details", message)
        self.assertNotIn("quarantine/uploads/private.pdf", message)

    def test_keeps_quality_fields_on_valid_sections(self) -> None:
        result = self._valid_result()

        validated = _validate_deep_parse_result(result)

        self.assertEqual(validated.sections[3]["quality_score"], 91)
        self.assertEqual(validated.sections[3]["quality"], {"overall_score": 91, "overall_needs_review": False})


class DeepParserProviderTests(TestCase):
    def _valid_deep_parse_result(
        self,
        *,
        summary: str = "合规的中文深度解析摘要，面向读者而不是解析器内部状态。",
        sections: list[dict[str, object]] | None = None,
        figures: list[dict[str, object]] | None = None,
        formulas: list[dict[str, object]] | None = None,
        code_suggestions: list[dict[str, object]] | None = None,
    ) -> DeepParseResult:
        return DeepParseResult(
            parser_name="stub_parser_v1",
            summary=summary,
            sections=sections
            if sections is not None
            else [
                {
                    "index": 1,
                    "title": "引言与研究背景",
                    "page_start": 1,
                    "page_end": 2,
                    "summary": "该部分概述研究背景和问题来源。",
                    "quality_score": 88,
                    "quality": {"overall_score": 88, "overall_needs_review": False},
                },
                {
                    "index": 2,
                    "title": "方法介绍",
                    "page_start": 3,
                    "page_end": 5,
                    "summary": "该部分解释方法结构和关键假设。",
                },
                {
                    "index": 3,
                    "title": "核心结果与结论",
                    "page_start": 6,
                    "page_end": 8,
                    "summary": "该部分整理实验结果和作者结论。",
                },
                {
                    "index": 4,
                    "title": "总结",
                    "page_start": None,
                    "page_end": None,
                    "summary": "该部分给出复现建议和核对重点。",
                },
            ],
            figures=figures
            if figures is not None
            else [{"id": "fig-stub", "caption": "Figure 1 shows the model overview.", "page": 4, "note": "需要核对图注。"}],
            formulas=formulas
            if formulas is not None
            else [{"id": "eq-stub", "latex": "u_t + u_x = 0", "text": "PDE residual", "note": "需要核对符号定义。"}],
            code_suggestions=code_suggestions
            if code_suggestions is not None
            else [
                {
                    "title": "复现实验入口",
                    "note": "优先检查官方仓库、数据集版本和随机种子。",
                    "score": 88,
                    "quality": {"overall_needs_review": False},
                    "needs_review": False,
                }
            ],
            reproduction_notes="复现时应核对数据集、指标、随机种子和硬件预算。",
        )

    def _high_quality_llm_markdown(self) -> str:
        long_background = (
            "这篇论文聚焦物理约束 Transformer 在偏微分方程长期预测中的稳定性问题，"
            "把传统 PINN 在长时间积分、边界条件保持、误差累积和多尺度动力学中的痛点串联起来。"
            "解析应明确指出作者要解决的不是单一网络结构替换，而是如何把 PDE 残差、观测数据、"
            "边界条件与序列建模能力组合成可训练的统一框架。论文动机还需要覆盖已有神经算子、"
            "PINN 与 Transformer 方法各自的局限，说明本文贡献在问题设定、模型设计和实验协议中的位置。"
        )
        long_method = (
            "方法部分需要完整解释输入时间片如何编码为 token、Transformer 模块如何捕捉空间时间相关性、"
            "物理残差 u_t + u u_x - nu u_xx = 0 如何并入损失函数，以及边界条件和初始条件如何约束训练。"
            "还要说明训练流程中数据项、物理项、正则项的权重关系，推理阶段如何从短窗口滚动到长时间预测，"
            "并把关键超参数、优化器、学习率、batch size、随机种子和停止准则写成可复现实验清单。"
            "如果有算法框图或伪代码，解析结果应将其转写为逐步 pipeline，而不是只写一句模型更有效。"
        )
        long_results = (
            "结果部分需要围绕 Burgers、Navier-Stokes 或其他 PDE benchmark 展开，列出数据划分、评价指标、"
            "相对 L2 误差、RMSE、基线模型和消融设置。解析应说明 Figure 2 展示预测场与误差图，Table 1 比较"
            "不同方法的数值结果，并指出优势是否来自物理损失、注意力结构、训练策略或数据规模。"
            "高质量细读还要标注哪些结论有表格和图支撑，哪些只是作者推断，避免把未验证泛化能力写成事实。"
        )
        long_summary = (
            "总结部分需要把论文贡献、适用边界、复现风险和下一步核对事项分开。应明确记录该方法依赖固定 PDE "
            "参数、数据生成协议和训练预算，迁移到新方程或更复杂边界时仍需重新验证。复现前必须锁定数据集版本、"
            "指标定义、硬件预算、随机种子、官方代码提交和 configs/ 中的超参数。最终结论应给出可执行的阅读建议："
            "先核对公式和算法流程，再复现实验主表，最后检查消融是否支持作者声称的机制。"
        )
        return f"""
# 深度解析质量评分: 92

## 引言与研究背景
{long_background}

## 方法介绍
{long_method}

```text
1. 读取 PDE 数据窗口并构造时空 token。
2. 用 Transformer 编码动态演化特征。
3. 计算数据误差、PDE 残差和边界条件损失。
4. 在固定随机种子和 benchmark 划分下训练并评估。
```

## 核心结果与结论
{long_results}

## 总结
{long_summary}

### 图表与公式
- Figure 2: predicted fields and absolute error on Burgers equation.
- Equation: u_t + u u_x - nu u_xx = 0.

### 复现建议
- scripts/train_burgers.py 和 configs/burgers_transformer.yaml 应固定数据、指标、消融和随机种子。
""".strip()

    def _quality_score_entries(self, result: DeepParseResult) -> list[dict[str, object]]:
        return [
            item
            for item in result.code_suggestions
            if "质量评分" in str(item.get("title", "")) or "quality" in str(item.get("title", "")).lower()
        ]

    def _fake_pdf_reader(self, text: str):
        class FakePage:
            def extract_text(self) -> str:
                return text

        class FakeReader:
            def __init__(self, path: str) -> None:
                self.path = path
                self.pages = [FakePage()]

        return FakeReader

    def _parse_with_storage_pdf(
        self,
        paper: Paper,
        *,
        pdf_text: str = "Abstract\nA local fallback text for PDE parsing.\nMethods\nu_t + u u_x - nu u_xx = 0.\n",
    ) -> DeepParseResult:
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / paper.source_pdf_path
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(b"%PDF-1.4\n% test pdf")
            with override_settings(STORAGE_ROOT=Path(tmpdir)), patch(
                "apps.papers.deep_parser.PdfReader",
                self._fake_pdf_reader(pdf_text),
            ):
                return LocalPdfDeepParserProvider().parse(DeepParserInput.from_paper(paper))

    def _assert_no_implementation_leakage(self, result: DeepParseResult) -> None:
        combined = "\n".join(
            [
                result.summary,
                result.reproduction_notes,
                "\n".join(str(section.get("summary", "")) for section in result.sections),
                "\n".join(str(item) for item in result.code_suggestions),
            ]
        ).lower()
        for leaked_word in ("pypdf", "upload", "storage", "placeholder"):
            self.assertNotIn(leaked_word, combined)

    def _assert_no_bare_tex_commands(self, markdown: str) -> None:
        without_code = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
        without_display_math = re.sub(r"\$\$.*?\$\$", " ", without_code, flags=re.DOTALL)
        without_inline_math = re.sub(r"\$[^$\n]+\$", " ", without_display_math)
        self.assertNotRegex(without_inline_math, r"\\(?:partial|mathcal|frac|nabla)\b")

    @patch("apps.papers.deep_parser.call_minimax_chat", create=True)
    def test_provider_prefers_llm_markdown_and_returns_complete_human_readable_sections(self, mocked_chat) -> None:
        mocked_chat.return_value = self._high_quality_llm_markdown()
        paper = Paper.objects.create(
            title="Physics-informed Transformer for PDE Forecasting",
            abstract="A transformer method for physics-informed PDE forecasting.",
            source_pdf_path="quarantine/uploads/paper.pdf",
        )

        result = self._parse_with_storage_pdf(paper)

        mocked_chat.assert_called_once()
        self.assertEqual(len(result.sections), 4)
        self.assertEqual(
            [section["title"] for section in result.sections],
            ["引言与研究背景", "方法介绍", "核心结果与结论", "总结"],
        )
        for section in result.sections:
            summary = str(section.get("summary", ""))
            self.assertGreaterEqual(len(summary), 240)
            self.assertRegex(summary, r"[\u4e00-\u9fff]")
        self.assertIn("Physics-informed Transformer", result.summary)
        self.assertIn("u_t + u u_x - nu u_xx = 0", str(result.formulas))
        self._assert_no_implementation_leakage(result)

    @patch("apps.papers.deep_parser.call_minimax_chat", create=True)
    def test_provider_records_high_quality_score_for_strong_llm_output(self, mocked_chat) -> None:
        mocked_chat.return_value = self._high_quality_llm_markdown()
        paper = Paper.objects.create(
            title="Physics-informed Transformer for PDE Forecasting",
            abstract="A transformer method for physics-informed PDE forecasting.",
            source_pdf_path="quarantine/uploads/paper.pdf",
        )

        result = self._parse_with_storage_pdf(paper)

        quality_entries = self._quality_score_entries(result)
        self.assertTrue(quality_entries, "Deep parse result should expose a quality-score suggestion.")
        self.assertGreaterEqual(max(int(entry.get("score", 0)) for entry in quality_entries), 80)
        self.assertFalse(any(item.get("needs_review") is True for item in quality_entries))

    @patch("apps.papers.deep_parser.call_minimax_chat", create=True)
    def test_provider_marks_low_quality_llm_output_as_needs_review_or_low_score(self, mocked_chat) -> None:
        mocked_chat.return_value = "## 摘要\n内容很少。"
        paper = Paper.objects.create(
            title="Under-specified PDE Note",
            abstract="Short note.",
            source_pdf_path="quarantine/uploads/short.pdf",
        )

        result = self._parse_with_storage_pdf(paper)

        quality_entries = self._quality_score_entries(result)
        self.assertTrue(quality_entries, "Low-quality deep parse should still include a quality assessment.")
        self.assertTrue(
            any(entry.get("needs_review") is True for entry in quality_entries)
            or max(int(entry.get("score", 100)) for entry in quality_entries) < 60,
            "Low-quality LLM output should be marked needs_review or receive a low quality score.",
        )

    @patch("apps.papers.deep_parser.call_minimax_chat", create=True)
    def test_provider_returns_saveable_needs_review_result_when_llm_fails(self, mocked_chat) -> None:
        mocked_chat.side_effect = RuntimeError("MiniMax unavailable")
        paper = Paper.objects.create(
            title="Physics-informed Transformer for PDE Forecasting",
            abstract="A transformer method for physics-informed PDE forecasting.",
            source_pdf_path="quarantine/uploads/paper.pdf",
        )

        result = self._parse_with_storage_pdf(paper)

        mocked_chat.assert_called_once()
        self.assertIsInstance(result, DeepParseResult)
        self.assertTrue(result.summary.strip())
        self.assertIsInstance(result.sections, list)
        self.assertGreaterEqual(len(result.sections), 1)
        self.assertTrue(result.reproduction_notes.strip())
        quality_entries = self._quality_score_entries(result)
        self.assertTrue(quality_entries, "Fallback result should explain low confidence through quality scoring.")
        self.assertIn("重新生成深度解析", str(quality_entries[-1].get("note", "")))
        self.assertNotIn("????", str(quality_entries[-1].get("note", "")))
        self.assertTrue(
            any(entry.get("needs_review") is True for entry in quality_entries)
            or max(int(entry.get("score", 100)) for entry in quality_entries) < 60,
        )

    def test_local_pdf_provider_reads_storage_pdf_and_extracts_real_deep_parse_signals(self) -> None:
        pdf_text = (
            "Abstract\nWe study physics-informed transformers for PDEs.\n"
            "Introduction\nNeural PDE solvers need long horizon stability.\n"
            "Methods\nThe loss enforces u_t + u u_x - nu u_xx = 0 and boundary conditions.\n"
            "Experiments\nWe evaluate on Burgers equation and Navier-Stokes.\n"
            "Figure 2 shows predicted fields and absolute error.\n"
            "Results\nThe method reduces relative L2 error by 35 percent.\n"
            "Conclusion\nLocal extraction gives useful reproduction hints.\n"
            "References\n"
        )

        class FakePage:
            def extract_text(self) -> str:
                return pdf_text

        class FakeReader:
            def __init__(self, path: str) -> None:
                self.path = path
                self.pages = [FakePage()]

        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/pinnsformer.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(b"%PDF-1.4\n% test pdf")
            paper = Paper.objects.create(
                title="PINNsFormer for Burgers Equation",
                abstract="We propose a transformer framework for physics-informed neural networks.",
                source_pdf_path="quarantine/uploads/pinnsformer.pdf",
            )
            parser_input = DeepParserInput.from_paper(paper)

            with override_settings(STORAGE_ROOT=Path(tmpdir)), patch("apps.papers.deep_parser.PdfReader", FakeReader), patch("apps.papers.deep_parser.call_minimax_chat", side_effect=RuntimeError("LLM disabled in test")):
                result = LocalPdfDeepParserProvider().parse(parser_input)

        self.assertEqual(result.parser_name, "local_pdf_deep_v1")
        self.assertNotIn("placeholder", result.summary.lower())
        self.assertEqual(len(result.sections), 4)
        section_titles = [section["title"] for section in result.sections]
        self.assertEqual(
            section_titles,
            ["引言与研究背景", "方法介绍", "核心结果与结论", "总结"],
        )
        for section in result.sections:
            self.assertIsInstance(section.get("evidence"), list)
            self.assertGreaterEqual(len(section["evidence"]), 1)
            self.assertTrue(str(section["summary"]).strip())
            self.assertNotIn("placeholder", str(section["summary"]).lower())
            self.assertGreaterEqual(len(str(section["summary"])), 420)
            self.assertRegex(str(section["summary"]), r"[\u4e00-\u9fff]")
        self.assertNotIn("pypdf", result.summary.lower())
        self.assertNotIn("upload", result.summary.lower())
        self.assertNotIn("storage", result.summary.lower())
        self.assertNotIn("placeholder", result.summary.lower())
        self.assertNotIn("pypdf", result.reproduction_notes.lower())
        self.assertNotIn("storage", result.reproduction_notes.lower())
        self.assertTrue(any("```text" in str(section["summary"]) for section in result.sections))
        self.assertTrue(any("###" in str(section["summary"]) for section in result.sections))
        self.assertRegex(result.reproduction_notes, r"[\u4e00-\u9fff]")
        self.assertTrue(any("u_t" in item.get("text", "") for item in result.formulas))
        self.assertTrue(any("Figure 2" in item.get("caption", "") for item in result.figures))
        self.assertGreaterEqual(len(result.code_suggestions), 1)
        self.assertIn("数据集或基准", result.reproduction_notes)
        self.assertIn("评价指标", result.reproduction_notes)
        self.assertIn("消融", result.reproduction_notes)
        self.assertIn("随机种子", result.reproduction_notes)

    def test_default_provider_is_local_pdf_not_placeholder(self) -> None:
        with override_settings(PAPER_DEEP_PARSER_PROVIDER="local_pdf"):
            self.assertIsInstance(get_deep_parser_provider(), LocalPdfDeepParserProvider)

        with override_settings(PAPER_DEEP_PARSER_PROVIDER="placeholder"):
            provider = get_deep_parser_provider()

        self.assertIsInstance(provider, LocalPdfDeepParserProvider)
        self.assertEqual(provider.parser_name, "local_pdf_deep_v1")

    def test_weak_evidence_sections_name_missing_checks_without_placeholder(self) -> None:
        pdf_text = "Abstract\nA short paper studies a solver.\nConclusion\nMore validation is needed."

        class FakePage:
            def extract_text(self) -> str:
                return pdf_text

        class FakeReader:
            def __init__(self, path: str) -> None:
                self.pages = [FakePage()]

        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/short.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(b"%PDF-1.4\n% test pdf")
            paper = Paper.objects.create(title="Short Solver Note", source_pdf_path="quarantine/uploads/short.pdf")

            with override_settings(STORAGE_ROOT=Path(tmpdir)), patch("apps.papers.deep_parser.PdfReader", FakeReader), patch("apps.papers.deep_parser.call_minimax_chat", side_effect=RuntimeError("LLM disabled in test")):
                result = LocalPdfDeepParserProvider().parse(DeepParserInput.from_paper(paper))

        self.assertEqual([section["title"] for section in result.sections], [
            "引言与研究背景",
            "方法介绍",
            "核心结果与结论",
            "总结",
        ])
        for section in result.sections:
            summary = str(section["summary"]).lower()
            self.assertNotIn("placeholder", summary)
            self.assertIn("核对", str(section["summary"]))
            self.assertGreaterEqual(len(section["evidence"]), 1)

    @patch("apps.papers.deep_processing.get_deep_parser_provider")
    def test_deep_worker_persists_provider_output(self, mocked_get_provider) -> None:
        outer = self

        class StubProvider:
            def parse(self, parser_input: DeepParserInput) -> DeepParseResult:
                return outer._valid_deep_parse_result(summary=f"解析 {parser_input.title} 的合规中文摘要。")

        mocked_get_provider.return_value = StubProvider()
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.LIGHT_READY)
        task = TaskRecord.objects.create(
            task_type="deep_process_paper",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        run_paper_deep_process_task.run(paper.id, task.id)

        profile = paper.deep_profiles.get(is_active=True)
        self.assertEqual(profile.parser_name, "stub_parser_v1")
        self.assertEqual(profile.summary, "解析 PINNsFormer 的合规中文摘要。")
        self.assertEqual([section["title"] for section in profile.sections], ["引言与研究背景", "方法介绍", "核心结果与结论", "总结"])
        self.assertEqual(profile.sections[0]["quality_score"], 88)
        self.assertEqual(profile.sections[0]["quality"], {"overall_score": 88, "overall_needs_review": False})
        self.assertEqual(profile.figures[0]["caption"], "Figure 1 shows the model overview.")
        self.assertEqual(profile.formulas[0]["latex"], "u_t + u_x = 0")
        self.assertEqual(profile.code_suggestions[0]["note"], "优先检查官方仓库、数据集版本和随机种子。")
        self.assertEqual(profile.reproduction_notes, "复现时应核对数据集、指标、随机种子和硬件预算。")

    @patch("apps.papers.deep_processing.get_deep_parser_provider")
    def test_deep_worker_rejects_sections_missing_required_schema(self, mocked_get_provider) -> None:
        class BrokenProvider:
            def parse(inner_self, parser_input: DeepParserInput) -> DeepParseResult:
                return self._valid_deep_parse_result(
                    sections=[
                        {
                            "index": "1",
                            "title": "引言与研究背景",
                            "page_start": 1,
                            "page_end": 2,
                            "summary": "该部分概述研究背景。",
                        },
                        {
                            "index": 2,
                            "title": "方法介绍",
                            "page_start": None,
                            "page_end": None,
                        },
                    ]
                )

        mocked_get_provider.return_value = BrokenProvider()
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.LIGHT_READY)
        paper.light_profiles.create(version=1, is_active=True, generator="rule_based_v1", background="stable background")
        task = TaskRecord.objects.create(
            task_type="deep_process_paper",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        with self.assertRaises(ValueError):
            run_paper_deep_process_task.run(paper.id, task.id)

        task.refresh_from_db()
        self.assertIn("sections[0].index must be an integer", task.error)
        self.assertIn("sections[1].summary is required", task.error)
        self.assertEqual(paper.deep_profiles.count(), 0)

    @patch("apps.papers.deep_processing.get_deep_parser_provider")
    def test_deep_worker_rejects_nested_items_missing_required_schema(self, mocked_get_provider) -> None:
        class BrokenProvider:
            def parse(inner_self, parser_input: DeepParserInput) -> DeepParseResult:
                return self._valid_deep_parse_result(
                    figures=[{"id": "fig-1", "page": 2, "note": "missing caption"}],
                    formulas=[{"id": "eq-1", "note": "missing latex and text"}],
                    code_suggestions=[{"title": "Missing note"}],
                )

        mocked_get_provider.return_value = BrokenProvider()
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.LIGHT_READY)
        paper.light_profiles.create(version=1, is_active=True, generator="rule_based_v1", background="stable background")
        task = TaskRecord.objects.create(
            task_type="deep_process_paper",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        with self.assertRaises(ValueError):
            run_paper_deep_process_task.run(paper.id, task.id)

        task.refresh_from_db()
        self.assertIn("figures[0].caption is required", task.error)
        self.assertIn("formulas[0].latex is required", task.error)
        self.assertIn("formulas[0].text is required", task.error)
        self.assertIn("code_suggestions[0].note is required", task.error)
        self.assertEqual(paper.deep_profiles.count(), 0)

    @patch("apps.papers.deep_processing.get_deep_parser_provider")
    def test_deep_worker_rejects_provider_output_with_internal_path_leakage(self, mocked_get_provider) -> None:
        class BrokenProvider:
            def parse(inner_self, parser_input: DeepParserInput) -> DeepParseResult:
                return self._valid_deep_parse_result(
                    summary="source_pdf_path 指向 quarantine/uploads/private.pdf 的内部调试信息。",
                    sections=[
                        {
                            "index": 1,
                            "title": "引言与研究背景",
                            "page_start": 1,
                            "page_end": 2,
                            "summary": "这里泄露了 source_pdf_path 和 quarantine/uploads/private.pdf。",
                        }
                    ],
                )

        mocked_get_provider.return_value = BrokenProvider()
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.LIGHT_READY)
        paper.light_profiles.create(version=1, is_active=True, generator="rule_based_v1", background="stable background")
        task = TaskRecord.objects.create(
            task_type="deep_process_paper",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        with self.assertRaises(ValueError):
            run_paper_deep_process_task.run(paper.id, task.id)

        task.refresh_from_db()
        self.assertIn("summary contains internal provider or storage details", task.error)
        self.assertIn("sections[0].summary contains internal provider or storage details", task.error)
        self.assertNotIn("quarantine/uploads/private.pdf", task.error)
        self.assertEqual(paper.deep_profiles.count(), 0)

    @patch("apps.papers.deep_processing.get_deep_parser_provider")
    def test_deep_worker_rejects_malformed_provider_output(self, mocked_get_provider) -> None:
        class BrokenProvider:
            def parse(self, parser_input: DeepParserInput) -> DeepParseResult:
                return DeepParseResult(
                    parser_name="broken_parser_v1",
                    summary="",
                    sections="not-a-list",  # type: ignore[arg-type]
                    figures=[],
                    formulas=[],
                    code_suggestions=[],
                    reproduction_notes="",
                )

        mocked_get_provider.return_value = BrokenProvider()
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.LIGHT_READY)
        light_profile = paper.light_profiles.create(
            version=1,
            is_active=True,
            generator="rule_based_v1",
            background="stable background",
        )
        task = TaskRecord.objects.create(
            task_type="deep_process_paper",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        with self.assertRaises(ValueError):
            run_paper_deep_process_task.run(paper.id, task.id)

        paper.refresh_from_db()
        task.refresh_from_db()
        light_profile.refresh_from_db()
        self.assertEqual(paper.status, Paper.Status.LIGHT_READY)
        self.assertTrue(light_profile.is_active)
        self.assertEqual(task.status, TaskRecord.Status.FAILED)
        self.assertEqual(task.stage, "failed")
        self.assertIn("Invalid deep parse result", task.error)
        self.assertEqual(paper.deep_profiles.count(), 0)

    @patch("apps.papers.deep_processing.get_deep_parser_provider")
    def test_deep_worker_rejects_schema_drift_inside_provider_output(self, mocked_get_provider) -> None:
        class BrokenProvider:
            def parse(self, parser_input: DeepParserInput) -> DeepParseResult:
                return DeepParseResult(
                    parser_name="broken_parser_v1",
                    summary="Parsed summary.",
                    sections=[{"index": 1, "page_start": 3}],
                    figures=[{"id": "fig-1"}, {"id": "fig-1"}],
                    formulas=[{"id": "eq-1", "latex": object()}],
                    code_suggestions=[{"note": "missing title"}],
                    reproduction_notes="Reproduction notes.",
                )

        mocked_get_provider.return_value = BrokenProvider()
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.LIGHT_READY)
        paper.light_profiles.create(
            version=1,
            is_active=True,
            generator="rule_based_v1",
            background="stable background",
        )
        task = TaskRecord.objects.create(
            task_type="deep_process_paper",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        with self.assertRaises(ValueError):
            run_paper_deep_process_task.run(paper.id, task.id)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskRecord.Status.FAILED)
        self.assertIn("sections[0].title is required", task.error)
        self.assertIn("figures id values must be unique", task.error)
        self.assertIn("formulas[0].latex must be JSON-safe", task.error)
        self.assertIn("code_suggestions[0].title is required", task.error)
        self.assertEqual(paper.deep_profiles.count(), 0)
