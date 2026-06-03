# 变更记录

本文记录 A510 知识库的重要系统版本。运行数据、私密配置、备份、成员信息和私有 PDF 保留在服务器或受控存储中，不写入本文。

## v0.4.4 - 2026-06-02

### 新增与修正

- 将 `release.json` 和 `backend/release.json` 同步到 `v0.4.4`，清理历史乱码，保证 `/api/health/` 展示干净的中文版本信息。
- 将深色主题设为默认视觉方向，并形成蓝金高亮体系：侧边栏使用金色文字高亮，主行动和焦点状态使用蓝色，提示与强调信息使用金色。
- 将色彩、边框、框体、按钮、关键词标签和主题切换位置的规范补入 UI 标准文档，作为后续页面扩展的统一依据。
- 修复关键词标签等局部深色背景下的可读性问题，避免深色主题中出现黑字、低对比文字或不可辨认的边框。
- 重写损坏的核心文档入口，统一中文文档边界、版本管理流程和功能状态说明。

### 部署说明

- 本版本不包含数据库结构变更。
- 部署后需要重启 `web` 服务，使 Django 重新读取 release metadata。

## v0.4.3 - 2026-05-26

### 变更

- 前端视觉层尝试向极简风格收敛：灰阶优先色彩、更紧的网格、克制排版、简化导航和重点页面降噪。
- 新增 `frontend/src/styles/minimal.css` 作为视觉系统样式层。
- 统一检索、阅读与复现、实验复现等页面完成第一轮简化。

### 备注

该版本后续经人工审查后认为仍不符合研究工作台的长期审美标准。后续版本改由本地私有 UI 标准继续约束和调整。

## v0.4.2 - 2026-05-26

### 变更

- 侧边栏开始按工作台、核心资料、研究工作流、管理治理分组。
- 统一检索改为更聚焦的命令面板和紧凑结果行。
- 论文详情的阅读与复现面板重组为状态、计划、复核和关联实验。
- 实验复现页面开始使用 workbench layout，覆盖项目创建、项目列表、protocol review 和 run records。
- 新增 UI polish 设计和实施记录；该类本地评审材料后续不进入 GitHub 核心仓库。

## v0.4.1 - 2026-05-26

### 新增

- 论文详情阅读面板支持编辑 next steps 和 due dates。
- 论文详情支持创建关联复现实验项目。
- 论文详情支持记录 light/deep profile review decision、score 和 notes。
- 实验页面支持创建 projects、添加 run records，并入队 run execution。
- 质量页面支持 acknowledge、resolve、dismiss issues。
- 知识空间详情路由展示第一版 direction-map frontend。
- 新增 `reindex_search` management command，用于手动重建 search index。

### 变更

- 搜索空状态说明如何重建索引，并链接到 tasks。
- Assistant 页面支持创建按 paper IDs 限定 scope 的 sessions。

## v0.4.0 - 2026-05-25

### 新增

- Paper reading state 和人工 reading-review records。
- Experiment and reproduction project 模块。
- 覆盖 papers、documents、experiments 的数据库统一搜索索引。
- Quality issue tracking 和轻量 audit queue。
- Scoped AI research assistant session/exchange 边界。
- Knowledge-space relation 和 direction-map snapshot 边界。
- 通过 `release.json`、`/api/health/` 和前端设置页展示系统 release metadata。

### 变更

- `/tasks` 对新异步工作流展示可读标签。
- 前端生产构建在 TypeScript/Vite 前运行 `check:hygiene`。

### 部署说明

- 引入数据库 migrations：`assistant.0001`、`papers.0006`、`experiments.0001`、`quality.0001`、`research_map.0001`、`search.0002`。
- 部署前已创建服务器私有备份；具体备份路径不写入 GitHub 文档。
