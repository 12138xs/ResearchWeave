from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from apps.ai.minimax import MiniMaxResponse
from apps.ai.views import estimate_message_tokens
from apps.ai.models import PaperQAExchange
from apps.library.models import Keyword
from apps.papers.models import Paper, PaperLightProfile


class PaperQATests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username="member", password="member-password")
        self.client.login(username=self.user.username, password="member-password")

    def test_logged_in_multi_paper_qa_requires_valid_csrf_token(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.login(username=self.user.username, password="member-password")
        csrf_response = client.get("/api/me/")
        csrf_token = csrf_response.json()["csrf_token"]
        paper = Paper.objects.create(title="CSRF selected paper", abstract="A selected paper.")

        with patch("apps.ai.views.call_minimax_chat") as mocked:
            mocked.return_value = MiniMaxResponse(
                content="基于选中论文回答。",
                model="MiniMax-M2.7",
                usage={"total_tokens": 24},
                raw={},
            )
            response = client.post(
                "/api/qa/papers/",
                {"paper_ids": [paper.id], "question": "请总结。", "mode": "compressed"},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scope"], "selected_papers")
        mocked.assert_called_once()

    def test_logged_in_multi_paper_qa_rejects_missing_csrf_token(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.login(username=self.user.username, password="member-password")
        paper = Paper.objects.create(title="CSRF selected paper", abstract="A selected paper.")

        with patch("apps.ai.views.call_minimax_chat") as mocked:
            response = client.post(
                "/api/qa/papers/",
                {"paper_ids": [paper.id], "question": "请总结。", "mode": "compressed"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)
        mocked.assert_not_called()

    def test_logged_in_current_paper_qa_requires_valid_csrf_token(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.login(username=self.user.username, password="member-password")
        csrf_response = client.get("/api/me/")
        csrf_token = csrf_response.json()["csrf_token"]
        paper = Paper.objects.create(title="CSRF current paper", abstract="A current paper.")

        with patch("apps.ai.views.call_minimax_chat") as mocked:
            mocked.return_value = MiniMaxResponse(
                content="基于当前论文回答。",
                model="MiniMax-M2.7",
                usage={"total_tokens": 24},
                raw={},
            )
            response = client.post(
                f"/api/qa/papers/{paper.id}/",
                {"question": "请总结。", "mode": "compressed"},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scope"], "single_paper")
        mocked.assert_called_once()

    def test_logged_in_current_paper_qa_rejects_missing_csrf_token(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.login(username=self.user.username, password="member-password")
        paper = Paper.objects.create(title="CSRF current paper", abstract="A current paper.")

        with patch("apps.ai.views.call_minimax_chat") as mocked:
            response = client.post(
                f"/api/qa/papers/{paper.id}/",
                {"question": "请总结。", "mode": "compressed"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)
        mocked.assert_not_called()

    def test_anonymous_multi_paper_qa_is_rejected(self) -> None:
        client = Client()
        paper = Paper.objects.create(title="Anonymous selected paper")

        with patch("apps.ai.views.call_minimax_chat") as mocked:
            response = client.post(
                "/api/qa/papers/",
                {"paper_ids": [paper.id], "question": "请总结。", "mode": "compressed"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)
        mocked.assert_not_called()

    def test_anonymous_current_paper_qa_is_rejected(self) -> None:
        client = Client()
        paper = Paper.objects.create(title="Anonymous current paper")

        with patch("apps.ai.views.call_minimax_chat") as mocked:
            response = client.post(
                f"/api/qa/papers/{paper.id}/",
                {"question": "请总结。", "mode": "compressed"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)
        mocked.assert_not_called()

    def test_answers_only_from_selected_papers_with_sources(self) -> None:
        pinn = Keyword.objects.create(name="PINN")
        selected = Paper.objects.create(
            title="PINNsFormer",
            year=2024,
            venue="ICLR",
            abstract="A transformer framework for physics-informed neural networks.",
        )
        selected.keywords.add(pinn)
        PaperLightProfile.objects.create(
            paper=selected,
            is_active=True,
            generator="rule_based_v1",
            keywords=["PINN", "Transformer"],
            background="传统 PINN 在长时间动力学中容易训练不稳定。",
            method="论文把物理约束和 Transformer 时序建模结合起来。",
            results="在多个 PDE 示例上提升了精度。",
            source_text_preview="PINNsFormer introduces a transformer-based architecture.",
        )
        unselected = Paper.objects.create(title="Unselected Paper", year=2023)

        with patch("apps.ai.views.call_minimax_chat") as mocked:
            mocked.return_value = MiniMaxResponse(
                content="这篇论文的核心方法是把 Transformer 引入 PINN，并用物理残差约束训练。",
                model="MiniMax-M2.7",
                usage={"total_tokens": 128},
                raw={},
            )
            response = self.client.post(
                "/api/qa/papers/",
                {
                    "paper_ids": [selected.id],
                    "question": "这篇论文的方法有什么特点？",
                    "mode": "compressed",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Transformer", payload["answer"])
        self.assertEqual(payload["model"], "MiniMax-M2.7")
        self.assertEqual(payload["usage"]["total_tokens"], 128)
        self.assertEqual([source["id"] for source in payload["sources"]], [selected.id])
        prompt = mocked.call_args.args[0][-1]["content"]
        self.assertIn("PINNsFormer", prompt)
        self.assertNotIn(unselected.title, prompt)

    def test_rejects_empty_question(self) -> None:
        paper = Paper.objects.create(title="Question target")

        response = self.client.post(
            "/api/qa/papers/",
            {"paper_ids": [paper.id], "question": " ", "mode": "compressed"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("question", response.json())

    def test_rejects_missing_papers(self) -> None:
        response = self.client.post(
            "/api/qa/papers/",
            {"paper_ids": [], "question": "总结这些论文", "mode": "compressed"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("paper_ids", response.json())

    def test_answers_current_paper_endpoint_without_other_papers(self) -> None:
        paper = Paper.objects.create(
            title="PINNsFormer",
            year=2024,
            venue="ICLR",
            abstract="Transformer-based PINN for PDEs.",
        )
        PaperLightProfile.objects.create(
            paper=paper,
            is_active=True,
            generator="minimax_m27_light_v1",
            keywords=["PINN", "Transformer"],
            background="论文关注 PINN 的时间依赖建模。",
            method="方法使用 Transformer 捕获伪序列中的依赖关系。",
            results="实验显示在多个 PDE 任务上更稳定。",
        )
        other = Paper.objects.create(title="Should Not Be In Prompt", year=2022)

        with patch("apps.ai.views.call_minimax_chat") as mocked:
            mocked.return_value = MiniMaxResponse(
                content="当前论文使用 Transformer 改进 PINN 的时间依赖建模。",
                model="MiniMax-M2.7",
                usage={"total_tokens": 96},
                raw={},
            )
            response = self.client.post(
                f"/api/qa/papers/{paper.id}/",
                {"question": "这篇论文解决了什么问题？", "mode": "compressed"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["scope"], "single_paper")
        self.assertEqual([source["id"] for source in payload["sources"]], [paper.id])
        prompt = mocked.call_args.args[0][-1]["content"]
        self.assertIn("PINNsFormer", prompt)
        self.assertNotIn(other.title, prompt)

    def test_current_paper_qa_persists_history_record(self) -> None:
        paper = Paper.objects.create(
            title="Persistent QA Paper",
            abstract="A paper with context.",
        )

        with patch("apps.ai.views.call_minimax_chat") as mocked:
            mocked.return_value = MiniMaxResponse(
                content="这是一次会被保存的回答。",
                model="MiniMax-M2.7",
                usage={"total_tokens": 42},
                raw={},
            )
            response = self.client.post(
                f"/api/qa/papers/{paper.id}/",
                {"question": "这篇论文解决了什么问题？", "mode": "compressed"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        exchange = PaperQAExchange.objects.get(paper=paper)
        self.assertEqual(exchange.user, self.user)
        self.assertEqual(exchange.question, "这篇论文解决了什么问题？")
        self.assertEqual(exchange.answer, "这是一次会被保存的回答。")
        self.assertEqual(exchange.mode, "compressed")
        self.assertEqual(exchange.model, "MiniMax-M2.7")
        self.assertEqual(exchange.usage["total_tokens"], 42)
        self.assertEqual(exchange.sources[0]["id"], paper.id)

    def test_current_paper_qa_history_endpoint_returns_recent_records(self) -> None:
        paper = Paper.objects.create(title="History Paper")
        PaperQAExchange.objects.create(
            paper=paper,
            user=self.user,
            question="第一个问题",
            answer="第一个回答",
            mode="compressed",
            model="MiniMax-M2.7",
            usage={"total_tokens": 12},
            sources=[{"id": paper.id, "title": paper.title, "used_sections": ["摘要"]}],
        )

        response = self.client.get(f"/api/qa/papers/{paper.id}/history/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["question"], "第一个问题")
        self.assertEqual(payload["results"][0]["answer"], "第一个回答")
        self.assertEqual(payload["results"][0]["sources"][0]["title"], "History Paper")

    @override_settings(MODEL_GATEWAY_CONTEXT_TOKEN_LIMIT=450)
    def test_preview_mode_falls_back_to_compressed_when_context_is_too_large(self) -> None:
        paper = Paper.objects.create(
            title="Long preview paper",
            abstract="A compact abstract.",
        )
        PaperLightProfile.objects.create(
            paper=paper,
            is_active=True,
            background="background " * 20,
            method="method " * 20,
            results="results " * 20,
            source_text_preview="preview " * 2000,
        )

        with patch("apps.ai.views.call_minimax_chat") as mocked:
            mocked.return_value = MiniMaxResponse(
                content="已基于压缩上下文回答。",
                model="MiniMax-M2.7",
                usage={"total_tokens": 32},
                raw={},
            )
            response = self.client.post(
                "/api/qa/papers/",
                {
                    "paper_ids": [paper.id],
                    "question": "请总结方法。",
                    "mode": "preview",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["requested_mode"], "preview")
        self.assertEqual(payload["mode"], "compressed")
        self.assertIn("回退", payload["context_warning"])
        prompt = mocked.call_args.args[0][-1]["content"]
        self.assertNotIn("preview preview preview", prompt)

    @override_settings(MODEL_GATEWAY_CONTEXT_TOKEN_LIMIT=220)
    def test_compressed_context_is_truncated_when_still_too_large(self) -> None:
        papers = []
        for index in range(2):
            paper = Paper.objects.create(
                title=f"Long compressed paper {index}",
                abstract="abstract " * 400,
            )
            PaperLightProfile.objects.create(
                paper=paper,
                is_active=True,
                background="background " * 500,
                method="method " * 500,
                results="results " * 500,
            )
            papers.append(paper)

        with patch("apps.ai.views.call_minimax_chat") as mocked:
            mocked.return_value = MiniMaxResponse(
                content="已基于截断上下文回答。",
                model="MiniMax-M2.7",
                usage={"total_tokens": 48},
                raw={},
            )
            response = self.client.post(
                "/api/qa/papers/",
                {
                    "paper_ids": [paper.id for paper in papers],
                    "question": "请比较这些论文。",
                    "mode": "compressed",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "compressed")
        self.assertIn("截断", payload["context_warning"])
        self.assertTrue(any("上下文已截断" in source["used_sections"] for source in payload["sources"]))
        prompt = mocked.call_args.args[0][-1]["content"]
        self.assertIn("[上下文已截断]", prompt)

    def test_token_estimator_is_conservative_for_chinese_text(self) -> None:
        messages = [{"role": "user", "content": "偏微分方程" * 100}]

        self.assertGreaterEqual(estimate_message_tokens(messages), 500)
