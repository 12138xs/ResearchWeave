# Research OS API 参考

Base URL 由部署环境决定。仓库文档统一使用相对路径：

```text
/api/
```

本文是当前 API surface 的人工维护地图。源码真实来源是 `backend/config/urls.py` 和各 app 的 `urls.py`。

大多数读接口用于团队内部浏览；写接口通常要求已登录 Django session，部分上传/处理接口还会校验允许的客户端网络。实现边界见 `docs/architecture/module-boundaries.md`：views 保持轻薄，查询进入 `selectors.py`，写入、任务入队、文件处理和事务边界进入 `services/`。

## 通用约定

- 读接口：除特别说明外，可保持内部公开浏览。
- 写接口：除特别说明外，要求登录。
- 返回结构不得暴露服务器绝对路径、storage 私有 key 或私有 PDF 位置。
- 错误响应应保持 DRF 结构，前端使用 `message`/字段错误展示。

## 健康检查

| 方法和路径 | 说明 |
| --- | --- |
| `GET /api/health/` | 检查 Django、PostgreSQL、pgvector、Redis，并返回 release metadata。 |

示例字段：

```json
{
  "status": "ok",
  "checks": {
    "django": "ok",
    "postgres": 1,
    "pgvector": true,
    "redis": true
  },
  "release": {
    "product": "A510知识库",
    "version": "v0.4.x"
  }
}
```

## 认证

| 方法和路径 | 说明 |
| --- | --- |
| `GET /api/me/` | 返回当前 session user。 |
| `POST /api/auth/login/` | 登录并写入 Django session cookie。 |
| `POST /api/auth/logout/` | 退出当前 session。 |

登录请求示例：

```json
{
  "username": "username",
  "password": "password"
}
```

## 论文

| 方法和路径 | 说明 | 写入权限 |
| --- | --- | --- |
| `GET /api/papers/` | DRF paper list，支持 `q`、`status`、`year`、`space`、`required_keywords`。 | 读 |
| `GET /api/papers/search/` | 论文库检索，支持阅读状态、复现状态、负责人、关键词、分页等筛选。 | 读 |
| `POST /api/papers/upload/` | 上传 PDF，执行校验并创建 post-upload task。 | 登录 + 允许网络 |
| `GET /api/papers/<id>/` | 返回论文详情、关键词、outline、light/deep profile 状态、active tasks 和 PDF 可用性。 | 读 |
| `PATCH /api/papers/<id>/` | 更新论文 metadata。 | 登录 |
| `POST /api/papers/<id>/metadata-suggestion/` | 请求元数据建议。 | 登录 |
| `POST /api/papers/<id>/light-process/` | 触发 AI粗读或规则粗读。 | 登录 |
| `POST /api/papers/<id>/trigger-deep-process/` | 触发 AI精读任务。 | 登录 |
| `GET /api/papers/<id>/deep-profiles/` | 获取精读 profile versions。 | 读 |
| `POST /api/papers/<id>/deep-profiles/<profile_id>/activate/` | 激活某个精读 profile。 | 登录 |
| `GET /api/papers/<id>/pdf/` | 下载或预览 PDF。响应层生成下载文件名，不暴露真实存储路径。 | 读 |

上传字段：

- `file`：必填 PDF。
- `title`：可选；为空时触发 metadata/title extraction，不把文件名作为最终标题。
- `year`、`venue`、`area`：可选 metadata。

上传约束：

- 只接受 PDF；
- 校验 PDF header、加密状态、页数和大小；
- 成功响应包含 `post_upload_task`；
- web-search 或 LLM 暂时不可用时，上传本身仍应成功。

## 阅读状态和人工复核

| 方法和路径 | 说明 | 写入权限 |
| --- | --- | --- |
| `GET /api/papers/<id>/reading-state/` | 返回阅读状态；不存在时后端创建默认状态。 | 读 |
| `PATCH /api/papers/<id>/reading-state/` | 更新 reading status、reproduction status、owner、next step、due date。 | 登录 |
| `GET /api/papers/<id>/reading-reviews/` | 列出 AI粗读/AI精读人工复核记录。 | 读 |
| `POST /api/papers/<id>/reading-reviews/` | 创建复核记录。 | 登录 |
| `PATCH /api/papers/<id>/reading-reviews/<review_id>/` | 更新复核状态、评分、备注。 | 登录 |

## 论文问答

| 方法和路径 | 说明 |
| --- | --- |
| `POST /api/qa/papers/` | 跨论文 QA，最多 20 篇。 |
| `POST /api/qa/papers/<id>/` | 单篇论文 QA。 |
| `GET /api/qa/papers/<id>/history/` | 单篇论文 QA 历史。 |

回答必须尽量基于论文 metadata、摘要、AI profiles 和可用 evidence；不应编造来源。

## 实验与复现

| 方法和路径 | 说明 | 写入权限 |
| --- | --- | --- |
| `GET /api/experiments/` | 列出复现实验项目。 | 读 |
| `POST /api/experiments/` | 创建复现实验项目。 | 登录 |
| `GET /api/experiments/<id>/` | 获取项目详情。 | 读 |
| `PATCH /api/experiments/<id>/` | 更新项目状态、目标、protocol、repo、environment 等。 | 登录 |
| `GET /api/experiments/<id>/runs/` | 列出项目 run records。 | 读 |
| `POST /api/experiments/<id>/runs/` | 创建 run record。 | 登录 |
| `PATCH /api/experiments/runs/<run_id>/` | 更新 run 状态、params、metrics、artifacts、notes。 | 登录 |
| `POST /api/experiments/runs/<run_id>/execute/` | 创建 `TaskRecord` 并入队执行或检查。 | 登录 |

## 统一检索

| 方法和路径 | 说明 | 写入权限 |
| --- | --- | --- |
| `GET /api/search/` | 跨 papers、documents、experiments 检索 `SearchIndexEntry`。 | 读 |
| `POST /api/search/reindex/` | 创建重建索引任务。 | 登录 |

常用参数：

- `q`
- `scope`
- `space`
- `page`
- `page_size`

检索结果不得暴露服务器路径、storage path 或私有 PDF 路径。

## 质量治理

| 方法和路径 | 说明 | 写入权限 |
| --- | --- | --- |
| `GET /api/quality/issues/` | 查询质量问题，支持 `object_type`、`object_id`、`status`。 | 读 |
| `PATCH /api/quality/issues/<id>/` | 更新质量问题状态、备注和复核信息。 | 登录 |
| `POST /api/quality/audits/enqueue/` | 创建质量审计任务。 | 登录 |

## 研究助理

| 方法和路径 | 说明 | 写入权限 |
| --- | --- | --- |
| `GET /api/assistant/sessions/` | 列出研究助理 sessions。 | 读 |
| `POST /api/assistant/sessions/` | 创建 scoped session。 | 登录 |
| `GET /api/assistant/sessions/<id>/` | 获取 session 和 exchanges。 | 读 |
| `POST /api/assistant/sessions/<id>/messages/` | 向 session 发送问题并返回 answer/sources。 | 登录 |

助理必须限定 scope，并返回 sources；范围不足时应说明，而不是自由编造。

## 方向地图

| 方法和路径 | 说明 | 写入权限 |
| --- | --- | --- |
| `GET /api/knowledge-spaces/<id>/map/` | 获取知识空间方向关系和 snapshot。 | 读 |
| `POST /api/knowledge-spaces/<id>/map/generate/` | 创建方向地图生成任务。 | 登录 |

## 知识文档

| 方法和路径 | 说明 | 写入权限 |
| --- | --- | --- |
| `GET /api/documents/` | 文档列表。 | 读 |
| `POST /api/documents/` | 创建文档。 | 登录 |
| `GET /api/documents/<id>/` | 文档详情。 | 读 |
| `PUT /api/documents/<id>/` | 完整更新文档。 | 登录 |
| `PATCH /api/documents/<id>/` | 部分更新文档。 | 登录 |

文档写入应创建版本记录，具体规则见 `docs/FEATURES.md` 和 documents services。

## 文档导入

| 方法和路径 | 说明 | 写入权限 |
| --- | --- | --- |
| `GET /api/document-import-batches/` | 导入批次列表。 | 读 |
| `POST /api/document-import-batches/` | 创建导入批次。 | 登录 |
| `GET /api/document-import-batches/<id>/` | 导入批次详情。 | 读 |
| `PATCH /api/document-import-batches/<id>/` | 更新导入批次。 | 登录 |
| `POST /api/document-import-batches/<id>/enqueue/` | 入队处理导入批次。 | 登录 |
| `GET /api/document-import-candidates/` | 导入候选列表。 | 读 |
| `POST /api/document-import-candidates/` | 创建候选。 | 登录 |
| `GET /api/document-import-candidates/<id>/` | 候选详情。 | 读 |
| `PATCH /api/document-import-candidates/<id>/` | 更新候选。 | 登录 |
| `POST /api/document-import-candidates/<id>/approve/` | 批准候选并写入文档。 | 登录 |

## 知识空间

| 方法和路径 | 说明 | 写入权限 |
| --- | --- | --- |
| `GET /api/knowledge-spaces/` | 知识空间树或列表。 | 读 |
| `POST /api/knowledge-spaces/` | 创建知识空间。 | 登录 |
| `GET /api/knowledge-spaces/<id>/` | 知识空间详情。 | 读 |
| `PATCH /api/knowledge-spaces/<id>/` | 更新知识空间。 | 登录 |
| `POST /api/knowledge-spaces/<id>/move/` | 移动知识空间，需校验环。 | 登录 |
| `POST /api/knowledge-spaces/<id>/archive/` | 归档知识空间。 | 登录 |

## 关键词和目录聚合

| 方法和路径 | 说明 |
| --- | --- |
| `GET /api/catalog/stats/` | 目录统计。 |
| `GET /api/keywords/` | 关键词列表。 |
| `GET /api/keywords/suggest/` | 关键词建议。 |

## 存储

| 方法和路径 | 说明 | 写入权限 |
| --- | --- | --- |
| `POST /api/storage/upload-image/` | 上传文档图片。 | 登录 |
| `GET /api/assets/images/<filename>` | 读取图片资源。 | 读 |

## 任务

| 方法和路径 | 说明 |
| --- | --- |
| `GET /api/tasks/` | 任务列表。 |
| `GET /api/tasks/status/?ids=1,2` | 批量查询任务状态。 |
| `GET /api/tasks/<id>/` | 任务详情。 |

任务展示统一围绕 `TaskRecord`，所有异步入口应先创建 `TaskRecord` 再入队 Celery。
