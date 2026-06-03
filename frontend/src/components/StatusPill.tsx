const statusLabels: Record<string, string> = {
  checking: '检查中',
  ok: '正常',
  degraded: '异常',
  pending: '排队中',
  running: '运行中',
  success: '已完成',
  uploaded: '已上传',
  parsing: '解析中',
  light_processing: '生成概览',
  light_ready: '概览完成',
  deep_processing: '深度解析',
  deep_ready: '深度完成',
  needs_review: '待审核',
  failed: '失败',
  archived: '已归档',
  draft: '草稿',
  published: '已发布',
  planned: '已计划',
  completed: '已完成',
  blocked: '受阻',
  cancelled: '已取消',
  open: '待处理',
  acknowledged: '已确认',
  resolved: '已解决',
  dismissed: '已忽略',
  missing: '暂无代码',
  official: '官方实现',
  internal: '内部实现',
  both: '官方+内部'
};


export function statusText(value: string) {
  return statusLabels[value] ?? value;
}

export function StatusPill({ value }: { value: string }) {
  return <span className={`pill pill-${value}`}>{statusText(value)}</span>;
}

