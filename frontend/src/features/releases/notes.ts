// Append a truthful user-facing entry for every delivered change; newest first.
// Only deployed history belongs here. Planned capabilities remain explicit limitations.
export const releaseNotes = [
  {
    id: '20260915-feedback-layout', date: '2026-09-15', title: '固定意见箱布局，新增版本说明',
    reference: '随本页面发布',
    changes: ['固定意见箱页面宽度与输入框高度，长内容在框内滚动。', '功能选择菜单改为浮层，输入 @ 时不再撑大表单；预留提交提示区域。', '运行管理新增版本说明页面，按时间倒序展示已核实的修改摘要。'],
    limitations: ['版本说明由维护者随修改更新；不自动生成或宣称尚未完成的能力。']
  },
  {
    id: '20260915-feedback', date: '2026-09-15', title: '新增团队意见箱', reference: 'bad6bb2 · feedback-v1',
    changes: ['运行管理新增黄色高亮意见箱入口。', '登录成员可共享提交与查看意见，自动记录提交人和时间。', '支持 @功能关联与跳转、分页，以及重复请求防重。'],
    limitations: ['尚无回复、处理状态、投票及编辑删除界面。']
  },
  {
    id: '20260915-pdf-outline', date: '2026-09-15', title: 'PDF 目录增强检索', reference: '1a59e0e · r2c1-pdf-outline',
    changes: ['根据 PDF 原生目录匹配章节标题，生成结构片段；不匹配时使用页级回退。', '支持展开片段与原页链接，保留原始证据和文件。'],
    limitations: ['PDF 预览空白、部分标题归一化及非法索引参数问题已发现，尚未修复。', '不是完整的 PDF 版面与公式解析。']
  },
  {
    id: '20260915-document-structure', date: '2026-09-15', title: '知识文档结构检索', reference: 'f115822 · r2b-document-structure',
    changes: ['知识文档按标题层级建立片段，支持固定版本检索、同节补读与引用定位。', '新版本自动建立索引，原文保持不变。'],
    limitations: ['历史版本编辑器状态残留风险已记录，仍待修复。']
  },
  {
    id: '20260915-markdown-structure', date: '2026-09-15', title: 'Markdown 材料结构检索', reference: '82d2339 · r2a-markdown-structure',
    changes: ['研究材料中的 Markdown 按章节建立独立索引批次与片段。', 'Agent 可检索、补读并定位到固定批次的引用。'],
    limitations: ['结构化统一搜索仍未全部完成。']
  },
  {
    id: '20260915-category', date: '2026-09-15', title: '接入材料类别范围', reference: '63c347e · r1-category-scope',
    changes: ['类别复选框接入后端检索，上传材料可分类。', '申报书禁止内置模型及增强检索外发；新类别会话不注入个人 memory。'],
    limitations: ['完整外发审批流程尚未实现。']
  },
  {
    id: '20260915-workspace', date: '2026-09-15', title: '调整个人偏好与高级范围', reference: 'a16d718',
    changes: ['个人偏好移除新建实验记录区域，保留已有笔记编辑与共享。', '高级范围由材料编号调整为类别选择版面，后续由类别检索版本接通。'], limitations: []
  },
  {
    id: '20260915-navigation', date: '2026-09-15', title: '调整实验日志与提示词入口', reference: 'fcc0376',
    changes: ['实验与复现改名为实验日志，移入核心工作。', '研究进展、思路可行性、工作改进改为可不选的单选提示词下拉框。'],
    limitations: ['config 与终端输出导入、指标图表尚未实现。']
  },
  {
    id: '20260915-agent-preview', date: '2026-09-15', title: '内置科研 Agent 试用上线', reference: '9314814 · v0.5.0-preview.1',
    changes: ['正式入口增加内置科研 Agent、研究材料和查询子页面。', '使用 MiniMax M3 自动查找授权材料、补读、回答并支持追问与引用展开。'],
    limitations: ['目前采用关键词召回与模型辅助，尚未接入 embedding 向量检索。', '科研语义质量验收仍未通过，回答中的来源归属和适用条件需核对。']
  }
];
