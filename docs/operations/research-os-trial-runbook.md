# A510 知识库试运行手册

最后更新：2026-06-02。

本文是 GitHub 版通用试运行手册。真实服务器地址、SSH 用户、成员名单、账号文件、密码、备份目录和私有数据路径不写入本文；它们应由私有运维环境、服务器 `.env` 或受控 secrets 文件维护。

## 范围

试运行用于确认 A510 知识库在目标部署环境中可以被团队成员稳定使用，重点覆盖：

- 首页和主要页面可访问。
- 登录、登出、只读浏览和登录写入行为正常。
- 论文库、知识文档、知识体系、任务队列、统一检索、实验与复现、质量治理页面可打开。
- 异步任务能够创建、入队和展示状态。
- 版本信息和健康检查可读。

## 前置条件

- 部署环境已经准备好 `.env`。
- 真实账号和试运行密码保存在私有 secrets 文件中。
- 数据库、Redis、Nginx、Django、Celery workers 已启动。
- `PUBLIC_BASE_URL` 指向当前试运行入口。

## 安全规则

- 不在命令输出、文档或截图中记录真实密码、API key、成员初始密码、私有 PDF、数据库 dump 或 secrets 文件内容。
- 不运行任何 `docker network` 命令。
- 部署前必须运行 `deploy/preflight.sh`，并确认实验室客户端路由不使用 `dev br-*` 或 `docker0`。

## 试运行检查

健康检查：

```bash
curl -fsS "$PUBLIC_BASE_URL/api/health/"
```

服务检查：

```bash
docker compose ps --services
```

前端构建检查：

```bash
cd frontend
npm run build
```

后端基础检查：

```bash
cd backend
python manage.py check
python manage.py test config.tests.test_release_info
```

容器内核心测试示例：

```bash
docker compose exec -T web python manage.py test apps.papers.tests apps.documents.tests apps.tasks.tests
```

## 人工验收清单

- [ ] 打开 `PUBLIC_BASE_URL` 指向的入口。
- [ ] 首页加载正常，版本信息与 `/api/health/` 一致。
- [ ] 未登录状态可以只读浏览论文和知识文档。
- [ ] 未登录状态看不到或无法执行写操作。
- [ ] 登录后可以执行允许的写操作。
- [ ] `/papers`、`/docs`、`/knowledge-spaces`、`/tasks`、`/search`、`/experiments`、`/quality` 页面首屏正常。
- [ ] 任务队列能显示异步任务状态。
- [ ] 深色主题、侧边栏分组、关键词标签和右上角色系切换符合 UI 标准。

## 记录方式

试运行记录应写入私有运维记录或 release checklist，不写入 GitHub 文档。GitHub 只保留通用流程和不含敏感信息的缺陷修复说明。
