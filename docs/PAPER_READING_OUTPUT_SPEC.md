# 论文阅读输出规范

本文定义 A510 知识库中 AI粗读和 AI精读的生成内容契约。

## 目标

- AI粗读帮助研究者在约 30 秒内判断论文是否值得深入阅读，以及它应归入哪个知识空间。
- AI精读为组会讨论、复现实验规划、理论借鉴和 related work 写作提供结构化技术切片。
- 即使 PDF extraction 不完美，生成内容也必须有用，并明确标注不确定性，不能编造细节。

## 共享规则

- 输出语言：面向用户的总结使用中文；必要的英文技术术语可以保留。
- 证据纪律：说明观点来自 extracted text、metadata，还是专业推断。
- 不编造数字：定量结论必须来自原文，否则标记为未核验。
- 稳定结构：下游 UI 和 QA 不依赖 MinerU、Nougat 等具体 parser。
- 版本化：每次运行创建或保留 versioned profile；新生成不能静默覆盖历史证据。
- 上传自动化：PDF 上传后应排队 metadata completion，再排队 AI粗读。上传本身必须快速，不能因为 web-search 或 LLM 暂时不可用而失败。

## AI粗读

后端目标：`PaperLightProfile`。

主要场景：

- 每日 arXiv 跟踪；
- 大批量第一轮筛选；
- 本地搜索/索引构建；
- 判断 Wiki/knowledge category。

必需抽象字段：

| 字段 | 含义 | 当前存储 |
| --- | --- | --- |
| `research_background` | 研究背景：领域问题、已有方法痛点、本文目标和知识类别 | `background` |
| `method_principle` | 方法原理：核心直觉、模型/算法流程、物理约束或实验设计思路 | `method` |
| `main_results` | 主要结果：核心发现、定量/定性结论、适用边界和待核验证据 | `results` |
| `keywords` | 规范关键词 | keyword relation 和 `keywords` |

### 粗读 Prompt 契约

AI generator 必须请求 Markdown，而不是 JSON。这样可以避免长中文 JSON 字符串被 LLM provider 截断或错误转义。

```markdown
## 研究背景

至少 2 段中文研究背景，每段不少于 80 个中文字符。

## 方法原理

至少 2 段中文方法原理，每段不少于 80 个中文字符。可使用 `$...$` 或 `$$...$$` 表示公式。

## 主要结果

至少 2 段中文主要结果，每段不少于 80 个中文字符，可使用 Markdown 列表组织结论。

## 关键词

- 关键词1
- 关键词2
- 关键词3
```

当前 `PaperLightProfile` 会把 Markdown sections 渲染到三个用户字段。字段只存正文，不存页面标题：

- `background` 对应页面标题 `研究背景`；
- `method` 对应页面标题 `方法原理`；
- `results` 对应页面标题 `主要结果`。

### 粗读质量门禁

- `background`、`method`、`results` 每项至少包含两段有信息量的内容。
- MiniMax response 必须包含完整 Markdown 标题：`## 研究背景`、`## 方法原理`、`## 主要结果`、`## 关键词`。
- 段落必须完整、具体、对研究者有用；一行碎片不可接受。
- 存储字段不得重复包含 `研究背景`、`方法原理`、`主要结果` 等 section headings。
- 存储内容应以中文为主。长英文 provider output、损坏 Markdown、缺失标题或单段输出必须拒绝原样持久化。
- `background` 必须说明研究上下文、痛点、目标和建议分类。
- `method` 必须解释方法原理，不能只是复述标题。
- `results` 必须区分已验证发现、局限和缺失证据。
- AI 输出过短、格式损坏或不完整时，fallback 必须扩展为保守结构化摘要。
- 上传触发的粗读生成与手动 `AI生成概览` 使用同一契约，不得引入单独的短模板。

## AI精读

后端目标：`PaperDeepProfile`。

主要场景：

- 核心文献分析；
- 组会准备；
- 复现实验规划；
- related work 素材抽取。

必需抽象字段：

| Section | 含义 | 当前存储 |
| --- | --- | --- |
| `introduction_background` | 引言、研究动机、问题背景、已有方法痛点和本文目标 | `sections` |
| `method_introduction` | 方法原理、模型或算法流程、物理约束、损失函数和关键实现逻辑 | `sections` |
| `core_results_conclusion` | 实验设置、核心结果、主要结论、图表证据和消融实验 | `sections` |
| `summary` | 全文总结、贡献边界、局限性、可复现风险和后续建议 | `sections` 和 `reproduction_notes` |
| `figures` | figure/table candidates 和解释说明 | `figures` |
| `formulas` | formula candidates，尽量包含 text/LaTeX | `formulas` |
| `code_suggestions` | reproduction entrypoints、config needs、official/internal code hints | `code_suggestions` |
| `reproduction_notes` | 复现或验证论文的实践注意事项 | `reproduction_notes` |

### 精读 Markdown 契约

LLM 或未来 parser 产生 Markdown 时，应遵循以下结构：

```markdown
## 引言与研究背景

### 原文直译式要点

1. 尽可能保留引言、方法、实验或结论中的原文核心句，并给出中文直译式理解。
2. 每条都要能追溯到论文文本；不能把模型推断写成论文事实。

### 梳理与扩展

用中文解释研究问题、动机、已有方法痛点、本文目标和适用范围。

### 核对建议

列出需要人工核对的页码、公式、图表或实验设定。

## 方法介绍

### 原文直译式要点
...

### 梳理与扩展
...

### 算法/流程草图
...

### 核对建议
...

## 核心结果与结论

### 原文直译式要点
...

### 梳理与扩展
...

### 核对建议
...

## 总结

### 原文直译式要点
...

### 梳理与扩展
...

### 复现风险和后续建议
...
```

### 精读质量门禁

- 每个一级 section 必须存在。
- 每个 section 必须区分原文证据、梳理解释和核对建议。
- 不得保存空 section、模板占位符或“待补充”。
- 公式和图表可不完整，但必须说明来源和不确定性。
- 复现建议必须具体到可能的数据、代码、环境、指标或失败风险。
- Deep profile 必须 versioned；激活新版本不能删除旧版本。
- Deep processing 不得修改论文 identity metadata。身份字段修改归 metadata patch 或专门 service。

## 前端展示要求

- 粗读结果按 `研究背景`、`方法原理`、`主要结果` 展示。
- 精读结果按四段结构展示，并允许折叠长内容。
- 渲染 Markdown、LaTeX、代码块时使用共享组件，不在页面里重复实现解析逻辑。
- 对低置信或 fallback 内容显示 warning，而不是假装完全可靠。
- 页面不展示 parser/provider 内部字段，除非用于错误排查。

## 失败和回退

- Provider 超时、输出截断、结构缺失、语言不符合要求时，任务应记录可见失败或 warning。
- 粗读可生成保守 fallback；fallback 必须明确证据不足。
- 精读若 evidence 不足，应失败或低置信保存，不应生成空泛长文。
- 所有失败都应能在 `/tasks` 或论文详情任务状态中追踪。
