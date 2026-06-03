# 团队文档工作流

本文说明 A510 知识库中团队知识文档的组织、导入、审核和未来导出边界。当前功能状态见 `docs/FEATURES.md`，API 细节见 `docs/API_REFERENCE.md`。

## 知识空间

Knowledge Spaces 是团队文档的正式层级，用于承载稳定的知识领域、课程主题、项目方向和运维专题。团队文档应归入合适的 space，而不是依赖零散标签或个人目录组织。

层级应保持清晰可读。一般优先使用两到三层；只有当领域确实复杂、团队成员能够稳定维护时，再继续细分。

## 知识文档

Documents 是 PostgreSQL 中的正式团队笔记。正文通过 `DocumentVersion` 记录版本，`Document` 保存标题、摘要、状态、所属 Knowledge Space、关键词等 metadata。

Markdown 是编辑、预览和导出的格式，但不是文件写入源。系统可信写入源是 Django/PostgreSQL；生成的 Markdown 文件只能作为交换、备份或个人使用副本，不能反向覆盖团队库。

## 批量导入

外部 URL 或整理好的资料先进入 import batch。系统会把每个来源记录为可追溯 source，再由 AI 生成候选中文 Markdown 草稿。

当前阶段不提供前端“批量导入草稿”页面。批量导入通过 API、脚本或后续内部工具完成；前端只负责正式文档和知识体系管理。这样可以先稳定接口、审计和安全边界，再决定是否提供可视化导入页面。

核心 API：

- `POST /api/document-import-batches/`：创建导入批次，可传入 `name`、`source_mode`、`target_space_id` 和 `sources`。
- `POST /api/document-import-batches/{id}/enqueue/`：提交 AI 候选草稿生成任务。
- `GET /api/document-import-candidates/?batch_id={id}`：查看候选草稿。
- `POST /api/document-import-candidates/{id}/approve/`：采纳候选草稿，生成正式文档草稿。

候选草稿不会自动发布。成员需要先检查标题、摘要、正文、引用来源和适用 Knowledge Space，确认内容可靠、归属清楚、没有越权材料后，才能采纳为团队文档草稿。

API 调用示例：

```json
{
  "name": "Linux 入门资料",
  "source_mode": "urls",
  "target_space_id": 1,
  "sources": [
    {
      "source_type": "url",
      "title": "Linux Shell 教程",
      "url": "https://example.com/linux-shell",
      "attribution": "example.com"
    }
  ]
}
```

## 批量导入工具边界

GitHub 核心仓库只保留导入 API、后端服务和前端正式页面，不内置团队迁移脚本、外部平台抓取脚本或一次性数据整理工具。

如果团队需要批量创建导入批次，应通过 `POST /api/document-import-batches/` 提交 JSON payload，再通过 `POST /api/document-import-batches/{id}/enqueue/` 触发候选草稿生成。命令行封装、外部平台抓取、历史数据迁移和本地 URL 清单处理属于私有维护工具，应放在仓库外部的本地运维目录中。

URL 清单、中文批次名、来源说明和人工整理备注应使用 UTF-8 文本或 JSON 文件保存，再由私有工具或调用方转换为 API payload。不要把团队内部来源清单、浏览器抓取脚本、外部平台快照或一次性迁移记录提交到 GitHub 仓库。

## 未来个人导出

个人 Obsidian、LLM Wiki 或其他个人知识库只作为未来单向导出目标。团队库可以导出给个人阅读、检索和再整理，但个人端编辑不会自动写回 PostgreSQL，也不会自动覆盖团队 Documents。

需要回流到团队库的个人修改，应通过人工提交、审阅和重新采纳完成。

## 安全和来源

- 不导入内网地址、本地服务地址、需要登录才能访问的私有资料。
- 不导入付费、受限、保密或授权不明确的内容。
- 外部资料必须保留来源归属，至少记录 URL、标题或出处说明。
- AI 生成内容只能作为草稿，发布前必须由人确认事实、版权和适用范围。
