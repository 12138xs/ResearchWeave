# 模块边界

最后更新：2026-06-01。

本文定义 A510 知识库的模块化和扩展边界，是未来 agent 和团队成员维护系统时的约束。本文本身不改变运行行为。

## 目标

- 保持 API 行为稳定，同时降低大文件耦合。
- Django views 保持轻薄：校验输入、调用 selectors/services、序列化输出。
- Celery tasks 保持轻薄：加载记录、调用 services、持久化任务状态。
- 可复用读取逻辑进入 selectors；会改变状态的业务用例进入 services。
- 避免从其他 app 的 `views.py` 或私有 helper 跨模块导入。
- 新增业务能力前先确认所属层级，避免把跨域编排塞回内容域 app。

## 后端层次

大型 app 应收敛为以下扁平结构：

```text
apps/<app>/
  models.py
  serializers.py
  urls.py
  views.py
  selectors.py
  services/
```

`selectors.py` 负责查询构造和只读聚合。Selectors 可以返回 querysets、model instances 或用于只读 API 响应的 plain dictionaries。

`services/` 负责写入、事务和工作流编排。Services 可以开启 transactions、锁定 rows、发布 Celery jobs，并在单一用例需要时调用其他 service modules。

`views.py` 不应包含长 transaction blocks、storage cleanup、profile version 重排或 task recovery 逻辑。迁移阶段允许保留少量 HTTP 专属 helper，例如 request parsing。

## App 职责

### 基础层

- `accounts`：session identity 和面向用户的 auth APIs。
- `common`：permissions 等小型横切 helper。
- `storage`：storage key 解析和公开文件服务 helper。
- `tasks`：通用 `TaskRecord` model 和 status APIs。除明确 Celery entrypoint modules 外，不应导入 paper、document、experiment、search、quality、assistant 或 map 工作流服务。
- `ai`：模型网关、usage 记录形态和 provider error normalization。业务上下文构造应放在领域 app（`papers`、`documents`）或跨域研究助理 `assistant` 中。

### 内容领域层

- `papers`：论文 metadata、PDF upload state、paper search、light/deep profiles、paper reading state、review records、paper task orchestration、PDF download names。
- `documents`：Markdown documents、document versions、source/import batches、candidate review、document import generation。
- `experiments`：复现实验 projects 和 experiment runs。可以引用 papers、documents 和 knowledge spaces，但这些 app 不应依赖 experiments 内部实现。
- `library`：knowledge spaces、keyword normalization、keyword suggestions 和 catalog-level read aggregation。

### 跨域编排层

- `search`：`SearchIndexEntry`，从内容领域 selectors 拉取只读 index projections。搜索结果不得暴露服务器路径、storage keys 或私有 PDF 位置。
- `quality`：`QualityIssue` 和 audit task orchestration。它只记录提示和人工复核状态，不应变成隐藏审批流。
- `assistant`：带 scope 的 research sessions 和 exchanges。回答必须返回 sources，不得在声明的 `scope_json` 外编造。
- `research_map`：knowledge-space relations 和 direction-map snapshots。复用 `library.KnowledgeSpace` 作为节点，不另建重复 taxonomy。

## 权限规则

- 内部读接口可以保持公开，方便团队浏览，除非功能说明另有要求。
- 写接口应要求登录 Django session。前端隐藏按钮只是体验优化；后端 views 必须负责强制校验。
- 对读公开、写登录的 API，优先使用 `apps.common.permissions.ReadOnlyOrAuthenticatedWriteMixin`。

## 依赖规则

- 不从其他 app 的 `views.py` 导入。
- 不导入其他模块的私有 helper，例如 `_set_document_keywords`。
- 需要跨模块共享的函数必须提升到 selector、service 或 public utility，并使用非私有名称。
- 跨域 dashboard 读取先放在 `library.selectors`，直到有独立 catalog app。
- 跨域 search 读取由来源 app 暴露为 `*_index_projection()` selectors，再由 `search.services` 拉取。
- 新前端模块必须新增 `frontend/src/api/<module>.ts` 和 `frontend/src/features/<module>/`；不要继续把新功能主体塞进 `frontend/src/app/LegacyApp.tsx`。
- 只做模块重构时，保持 migrations、API paths 和 response shapes 不变。

## 文档语言规则

- 模块说明、风险、验收、职责描述使用中文。
- 文件名、类名、函数名、API path、status enum、app label 可以保留英文。
- 新增或维护架构文档时，先更新本文，再更新低优先级实施记录，避免多处重复定义边界。

## 验证

每个重构批次后运行：

```bash
cd backend
python manage.py check

cd ../frontend
npm run build
```

依赖数据库的 Django tests 应在 Compose 环境内运行，因为默认 `POSTGRES_HOST=postgres` 是 Compose-only hostname：

```bash
docker compose exec -T web python manage.py test apps.library.tests apps.documents.tests apps.papers.tests.test_paper_upload apps.papers.tests.test_paper_deep_processing apps.ai.tests apps.tasks.tests
```

服务器只读健康检查：

```bash
curl -fsS --max-time 5 "$PUBLIC_BASE_URL/api/health/"
```
