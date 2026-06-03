# Release 管理

最后更新：2026-06-02。

本文说明 A510 知识库的轻量版本管理方式。GitHub 仓库只记录源码版本、文档版本和发布流程；真实服务器地址、SSH 用户、备份目录、成员文件和运行期密钥由私有运维环境维护，不写入 GitHub 文档。

## 管理范围

- 系统版本：由 `release.json`、`backend/release.json`、`docs/CHANGELOG.md` 和 `/api/health/` 共同记录。
- 内容版本：由业务模型维护，例如 `DocumentVersion`、`PaperLightProfile`、`PaperDeepProfile`、`DirectionMapSnapshot`，不写入系统 release。
- 运行证据：由服务器生成，例如 `current-release.json`、部署备份、服务状态和健康检查结果，不提交到仓库。

## 文件职责

| 文件 | 职责 | 维护要求 |
| --- | --- | --- |
| `release.json` | 项目根目录 release metadata | 每次系统发布必须更新 |
| `backend/release.json` | 后端构建上下文中的 release metadata | 必须和根目录 `release.json` 保持一致 |
| `docs/CHANGELOG.md` | 面向人的版本历史 | 每个版本新增一节，写清楚变化和部署注意事项 |
| `current-release.json` | 服务器运行期发布标记 | 由 `deploy/write_release_marker.sh` 生成，不提交 |
| `/api/health/` | 健康检查和当前 release 展示 | 部署后必须验证 |

## 版本号规则

使用 `vMAJOR.MINOR.PATCH`。

- `MAJOR`：需要团队明确协调的部署方式、数据模型或使用方式变化。
- `MINOR`：新增模块、可见工作流或较大范围能力。
- `PATCH`：bug fix、文档修正、UI 细节、运行维护和小型改进。

## Release 步骤

1. 从 GitHub `main` 同步最新源码，新建变更分支。
2. 更新 `release.json` 和 `backend/release.json`，保持字段完全一致。
3. 在 `docs/CHANGELOG.md` 顶部新增版本条目。
4. 如本次变更影响功能、API、UI 或运维流程，同步更新对应权威文档。
5. 运行本地检查。

```bash
cd backend
python manage.py check
python manage.py test config.tests.test_release_info

cd ../frontend
npm run build
```

6. 合并到 `main` 后创建 annotated tag。

```bash
git tag -a v0.4.5 -m "A510知识库 v0.4.5"
git push origin main
git push origin v0.4.5
```

7. 服务器部署前运行私有运维环境中的预检命令。

```bash
bash deploy/preflight.sh
ip route get "$RESEARCH_OS_ROUTE_PROBE"
```

路由结果不得包含 `dev br-*` 或 `docker0`。禁止运行任何 `docker network` 命令。

8. 部署后重启需要读取 release metadata 的服务，通常至少包括 `web`。
9. 写入运行期 marker。

```bash
bash deploy/write_release_marker.sh
```

10. 验证健康检查和版本信息。

```bash
curl -fsS "$PUBLIC_BASE_URL/api/health/"
cat current-release.json
```

## 三方事实源

| 位置 | 职责 | 不应保存 |
| --- | --- | --- |
| 本地工作区 | 开发、验证、提交 | 真实密钥、成员文件、数据库 dump、私有 PDF |
| GitHub | 源码和文档事实源 | `.env`、`secrets/`、`storage/`、备份、运行日志 |
| 服务器 | 运行状态事实源 | 未回写 GitHub 的源码热修 |

如果服务器上发生紧急热修，必须立即回写到本地和 GitHub，避免三方分叉。

## 文档一致性

- 版本摘要必须使用中文；命令、路径、API 和状态枚举保留英文或 ASCII。
- 不在 release 文档中写入 `.env`、密码、API key、成员信息、数据库转储、私有 PDF、导入数据内容、真实服务器 IP、个人本地路径或具体备份目录。
- 如果 release metadata 出现乱码，必须立即修正，并在 `docs/CHANGELOG.md` 记录为 patch 版本。
- 低优先级文档只补充事实或链接，不复制高优先级文档的大段内容。
