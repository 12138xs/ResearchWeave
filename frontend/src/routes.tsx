export type AppRoute = {
  path: string;
  label: string;
  description?: string;
};

export type NavGroup = {
  label: string;
  routes: AppRoute[];
};

export const navGroups: NavGroup[] = [
  {
    label: '工作台',
    routes: [
      { path: '/', label: '总览', description: '研究入口' },
      { path: '/search', label: '统一检索', description: '跨库检索' }
    ]
  },
  {
    label: '核心工作',
    routes: [
      { path: '/materials', label: '研究材料', description: '原文与证据' },
      { path: '/papers', label: '论文库', description: '阅读与复现' },
      { path: '/docs', label: '知识文档', description: '团队沉淀' }
    ]
  },
  {
    label: '研究流程',
    routes: [
      { path: '/experiments', label: '实验与复现', description: '实验记录' },
      { path: '/assistant', label: '研究助理', description: '有源辅助' }
    ]
  },
  {
    label: '管理支撑',
    routes: [
      { path: '/quality', label: '质量治理', description: '人工复核' },
      { path: '/knowledge-spaces', label: '知识体系', description: '分类结构' }
    ]
  },
  {
    label: '运行管理',
    routes: [
      { path: '/tasks', label: '任务队列', description: '异步进度' },
      { path: '/settings', label: '系统设置', description: '版本运行' }
    ]
  }
];

export const routes = navGroups.flatMap((group) => group.routes);
