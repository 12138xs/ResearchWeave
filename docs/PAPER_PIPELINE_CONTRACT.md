# 论文处理流程契约

最后更新：2026-06-01。

本文是 A510 知识库论文工作流的接口级契约：

```text
PDF 上传 -> quarantine storage -> 元数据抽取/补全 -> light profile -> AI粗读 -> AI精读
```

当实现和本文不一致时，先核验 `backend/apps/papers/` 当前代码，再在同一变更中更新低优先级文档或实现。本文不得写入真实密码、API key、私有 PDF 文本、数据库 dump、成员初始密码或 `.env` 内容。

## 真实来源

| 区域 | 当前来源 |
| --- | --- |
| API URLs | `backend/apps/papers/urls.py` |
| Endpoint 编排 | `backend/apps/papers/views.py` |
| API response keys | `backend/apps/papers/serializers.py`, `backend/apps/tasks/serializers.py` |
| Models | `backend/apps/papers/models.py`, `backend/apps/tasks/models.py` |
| 上传 PDF metadata extraction | `backend/apps/papers/metadata.py` |
| 上传后 metadata completion | `backend/apps/papers/post_upload.py`, `backend/apps/papers/metadata_completion.py` |
| 规则/AI light processing | `backend/apps/papers/light_processing.py` |
| Deep processing lifecycle | `backend/apps/papers/deep_processing.py` |
| Deep parser/provider contract | `backend/apps/papers/deep_parser.py` |
| Celery entrypoints | `backend/apps/papers/tasks.py` |
| 生成阅读输出 | `docs/PAPER_READING_OUTPUT_SPEC.md` |

## 稳定工作流

```text
POST /api/papers/upload/
  -> validate multipart PDF
  -> _safe_pdf_name()
  -> _save_quarantine_pdf()
  -> Paper(status="uploaded", source_pdf_path=<relative key>)
  -> TaskRecord(task_type="paper_upload_postprocess", queue="ai_q")
  -> metadata completion may fill empty/placeholder fields
  -> TaskRecord(task_type="paper_ai_light_process", queue="ai_q")
  -> PaperLightProfile(version=n, is_active=True)
  -> Paper.status="light_ready"
  -> optional POST /api/papers/<id>/trigger-deep-process/
  -> TaskRecord(task_type="deep_process_paper", queue="heavy_q")
  -> PaperDeepProfile(version=n, is_active=True)
  -> Paper.status="deep_ready"
```

## 存储 key 和文件命名

上传 PDF 由 `PaperUploadView` 通过 `_save_quarantine_pdf()` 存储。当前 key 模板：

```text
quarantine/uploads/<safe-stem>-<12-hex>.pdf
```

物理文件名由 `_safe_pdf_name(filename)` 创建：

```python
stem = filename.rsplit(".", 1)[0]
safe_stem = slugify(stem, allow_unicode=True) or "paper"
return f"{safe_stem[:80]}-{uuid4().hex[:12]}.pdf"
```

规则：

- `Paper.source_pdf_path` 只保存相对 storage key，例如 `quarantine/uploads/fourier-neural-operator-9f3a01bc88d2.pdf`。
- 完整物理路径只能在服务端解析为 `settings.STORAGE_ROOT / Paper.source_pdf_path`。
- 不得保存服务器 storage 绝对路径、个人本地绝对路径或任何可暴露运行环境的路径。
- 原文件 stem 只能在 `slugify(..., allow_unicode=True)`、80 字符截断、追加随机 12-hex 后使用。
- 随机后缀必须存在，即使文件名看似唯一。
- `12-hex` 是 `uuid4().hex[:12]`，用于避免碰撞，不是内容 hash；不得替换为顺序号、`Paper.id`、`PaperSerializer.code`、DOI、arXiv ID 或任何论文身份字段。
- `P000001` 等显示编号不得写入存储文件名。该编号由当前数据库排序生成，删除会释放/重算。
- 不把完整正式论文标题写入服务器文件名，避免超长、特殊字符、隐私泄露、path injection 和未来 rename 成本。
- 存储物理文件名上传后不可变。Metadata completion、人工编辑、AI粗读和 AI精读都不得重命名存储文件。
- 需要下载文件名时，在 response 层生成。当前 `PaperPdfView` 根据当前 `Paper.title` 生成下载名，必要时追加 year，失败时回退到 `paper.slug` 或 `paper.pk`；这不重命名原存储文件。

## 本地、服务器和仓库边界

| 位置 | 是否可存运行 PDF | 命名规则 | 是否可含 `P000001` | 是否可含完整标题 | 说明 |
| --- | --- | --- | --- | --- | --- |
| 服务器 runtime storage：`$STORAGE_ROOT/` | 是 | `quarantine/uploads/<safe-stem>-<12-hex>.pdf` | 否 | 否 | 真实运行来源，实际路径不写入仓库文档 |
| 本地 dev runtime storage：`storage/` | 仅本地测试 | 同服务器规则 | 否 | 否 | 不发布 |
| 仓库源码树 | 否，除非是小型脱敏 fixtures | fixture 名稳定且可解释 | 否 | 尽量避免 | 只用于测试 |

`LocalStorageProvider.ensure_runtime_dirs()` 可以在 `STORAGE_ROOT` 下创建 `quarantine/uploads`、`objects/pdf`、`objects/images`、`objects/figures`、`objects/attachments`、`snapshots/...`、`exports/...` 和 `tmp`。当前用户上传原始 PDF 只应位于 `quarantine/uploads/`。

## API 暴露规则

普通 list/detail 使用 `PaperSerializer`，暴露 `has_pdf` 和 `GET /api/papers/<id>/pdf/`，不暴露 `source_pdf_path`。

上传成功响应是例外：序列化 paper payload 中附加 `source_pdf_path` 和 `post_upload_task`。前端不得在普通列表、详情或生成笔记中展示 `source_pdf_path`。

## 标题和身份 metadata

论文身份字段包括：

- `title`
- `authors`
- `DOI`
- `arXiv ID`
- `source URL`
- `year`
- `venue`

标题规则：

- 标题应来自论文文本、DOI/arXiv/publisher 等证据，而不是下载文件名。
- 标题为空或明显是文件噪声时，上传后任务应尝试补全。
- `AI粗读` 和 `AI精读` 不得在生成阅读内容时擅自重写身份 metadata。
- 人工 metadata patch 是修改身份 metadata 的主要入口。

## 任务归属

所有异步入口必须先创建 `TaskRecord`，再入队 Celery。

常见任务：

- `paper_upload_postprocess`：上传后 metadata completion 和 AI粗读入队。
- `paper_ai_light_process`：生成或刷新 `PaperLightProfile`。
- `deep_process_paper`：生成 `PaperDeepProfile`。

任务失败必须写入可见错误状态，不能只在 worker log 中失败。

## AI粗读边界

AI粗读写入 `PaperLightProfile`，并可更新 paper status。输出契约见 `PAPER_READING_OUTPUT_SPEC.md`。

AI粗读可以使用：

- 当前 metadata；
- abstract；
- PDF extraction 的有限文本；
- metadata completion 结果；
- 领域分类和关键词建议。

AI粗读不得：

- 重命名 PDF 存储文件；
- 把文件名当作正式标题；
- 覆盖人工确认的身份 metadata；
- 存储空 profile 或一行 placeholder。

## AI精读边界

AI精读写入 `PaperDeepProfile`，并可更新 deep processing 状态。

AI精读可以存储：

- structured sections；
- figures；
- formulas；
- code suggestions；
- reproduction notes；
- quality score 和 warnings。

AI精读不得修改：

- title；
- authors；
- DOI；
- arXiv ID；
- source URL；
- PDF storage key。

## 质量和回退

- 如果 metadata completion、web-search 或 LLM 暂时失败，上传本身仍应成功，并记录 task failure 或 warning。
- 如果 AI 输出过短、结构损坏或缺少核心标题，后端应拒绝原样持久化，并生成保守结构化 fallback。
- Deep parser evidence 不足时，必须给出可见错误或低置信状态。
- 前端应能通过 `/tasks` 看到任务进度和失败原因。

## 验证

后端检查：

```bash
cd backend
python manage.py check
```

Compose 内测试示例：

```bash
docker compose exec -T web python manage.py test apps.papers.tests
```

重点回归项：

- 上传成功不暴露绝对路径；
- 空标题上传会进入 metadata/title extraction；
- 上传后任务会创建 `TaskRecord`；
- AI粗读写入版本化 `PaperLightProfile`；
- AI精读写入版本化 `PaperDeepProfile`；
- PDF 下载文件名在 response 层生成；
- 失败任务有用户可见状态。
