# 文档索引

最后更新：2026-06-02。

本文是 A510 知识库的系统文档地图。仓库入口说明见 `README.md`；本文只列出功能、API、架构、运行边界、版本历史和设计规范等系统文档。

## 权威顺序

1. `README.md`：项目定位、科研意义和核心功能概览。
2. `docs/FEATURES.md`：当前功能范围。
3. `docs/CHANGELOG.md`：系统版本历史。
4. `docs/operations/release-management.md`：版本管理流程。
5. `docs/API_REFERENCE.md`：API 地图。
6. `docs/architecture/module-boundaries.md`：模块边界。
7. `docs/architecture/runtime-boundaries.md`：运行边界。
8. `docs/PAPER_PIPELINE_CONTRACT.md`：论文处理流程契约。
9. `docs/PAPER_READING_OUTPUT_SPEC.md`：论文阅读输出规范。

## 文档目录

| 路径 | 用途 |
| --- | --- |
| `docs/architecture/` | 架构和运行边界 |
| `docs/operations/` | 通用运维流程 |

## 维护规则

- 当前事实写入权威文档，历史摘要不扩写。
- 过时文档若无独有事实，直接删除；若需要审计线索，迁入私有运维记录。
- `plans/` 只保留包含任务清单、文件范围和验证命令的可执行计划。
- `specs/` 只保留当前规范或仍被引用的设计约束。
- 面向 GitHub 读者的根入口只使用 `README.md`。
