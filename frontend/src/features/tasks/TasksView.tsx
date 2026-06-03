import { useEffect, useState } from 'react';

import { apiFetch, payloadMessage, readResponsePayload } from '../../api/client';
import { EmptyState } from '../../components/EmptyState';
import { Header } from '../../components/Header';
import { StatusPill } from '../../components/StatusPill';
import type { TaskListResponse } from './types';

const emptyTaskList: TaskListResponse = {
  summary: {
    total: 0,
    active: 0,
    has_active: false,
    by_status: {}
  },
  results: []
};

function taskStatusText(summary: TaskListResponse['summary']) {
  if (summary.active > 0) return `${summary.active} 个任务正在运行或排队`;
  if (summary.total > 0) return '最近任务已经处理完';
  return '暂无任务记录';
}

function formatFullDate(value?: string) {
  if (!value) return '未记录';
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value));
}

export function TasksView() {
  const [tasks, setTasks] = useState<TaskListResponse>(emptyTaskList);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function loadTasks() {
      try {
        const params = new URLSearchParams({ limit: '40', reload: String(refreshTick) });
        if (filter !== 'all') params.set('status', filter);
        const response = await apiFetch(`/api/tasks/?${params.toString()}`);
        const payload = await readResponsePayload(response);
        if (!response.ok) throw new Error(payloadMessage(payload, '任务队列暂时不可用。'));
        if (cancelled) return;
        const nextTasks = payload as TaskListResponse;
        setTasks(nextTasks);
        setError('');
        setLoading(false);
        const nextDelay = nextTasks.summary.has_active ? 2500 : 12000;
        timer = window.setTimeout(loadTasks, nextDelay);
      } catch (taskError) {
        if (cancelled) return;
        setError(taskError instanceof Error ? taskError.message : '任务队列暂时不可用。');
        setLoading(false);
        timer = window.setTimeout(loadTasks, 15000);
      }
    }

    setLoading(true);
    loadTasks();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [filter, refreshTick]);

  const counts = tasks.summary.by_status;

  return (
    <main className="page">
      <Header
        eyebrow="Operations"
        title="任务队列"
        description="跟踪论文入库、AI 粗读、AI 精读和文档导入任务；系统会按队列活跃度自动调整刷新频率。"
      />

      <section className="metric-grid task-metrics">
        <article className="metric-card">
          <span>活跃任务</span>
          <strong>{tasks.summary.active}</strong>
          <p>{taskStatusText(tasks.summary)}</p>
        </article>
        <article className="metric-card">
          <span>最近任务</span>
          <strong>{tasks.summary.total}</strong>
          <p>默认展示最近 40 条任务记录</p>
        </article>
        <article className="metric-card">
          <span>已完成</span>
          <strong>{counts.success ?? 0}</strong>
          <p>轻量处理、导入生成等成功任务</p>
        </article>
        <article className="metric-card">
          <span>失败</span>
          <strong>{counts.failed ?? 0}</strong>
          <p>失败任务会保留错误信息，便于回溯</p>
        </article>
      </section>

      <section className="task-toolbar">
        <div className="segmented">
          {[
            ['all', '全部'],
            ['pending', '排队中'],
            ['running', '运行中'],
            ['success', '已完成'],
            ['failed', '失败']
          ].map(([value, label]) => (
            <button type="button" className={filter === value ? 'active' : ''} key={value} onClick={() => setFilter(value)}>
              {label}
            </button>
          ))}
        </div>
        <button type="button" className="secondary-button" onClick={() => setRefreshTick((value) => value + 1)}>
          手动刷新
        </button>
      </section>

      {error && <div className="form-message form-message-error">{error}</div>}
      {loading ? (
        <EmptyState title="正在读取任务队列" note="如果刚刚重启服务，稍等几秒即可恢复。" />
      ) : tasks.results.length === 0 ? (
        <EmptyState title="暂无任务记录" note="上传论文并执行轻量处理后，这里会显示处理阶段、进度和结果。" />
      ) : (
        <section className="table-panel task-list">
          {tasks.results.map((task) => (
            <article className="task-row" key={task.id}>
              <div className="task-row-main">
                <div className="paper-title-row">
                  <span className="paper-code">T{String(task.id).padStart(4, '0')}</span>
                  <strong>{task.label}</strong>
                </div>
                <p>
                  {task.object_type || 'system'} {task.object_id ? `#${task.object_id}` : ''} / 阶段 {task.stage || '未记录'} / 更新 {formatFullDate(task.updated_at)}
                </p>
                {task.error && <p className="task-error">{task.error}</p>}
              </div>
              <div className="task-row-side">
                <StatusPill value={task.status} />
                <div className="task-progress" aria-label={`进度 ${task.progress}%`}>
                  <span style={{ width: `${Math.max(0, Math.min(100, task.progress))}%` }} />
                </div>
                <small>{task.progress}%</small>
              </div>
            </article>
          ))}
        </section>
      )}

      <section className="panel task-notes">
        <div className="section-heading">
          <div>
            <span>队列边界</span>
            <h2>当前执行策略</h2>
          </div>
        </div>
        <div className="flow">
          <div className="flow-step"><span>1</span><p>快速任务、AI 任务、重型解析任务分队列运行，避免 PDF 解析拖慢普通操作。</p></div>
          <div className="flow-step"><span>2</span><p>前端只读取 Django 任务状态，不直接访问 Redis、Celery 或文件系统。</p></div>
          <div className="flow-step"><span>3</span><p>有活跃任务时约 2.5 秒刷新一次；没有活跃任务时约 12 秒刷新一次。</p></div>
        </div>
      </section>
    </main>
  );
}

