import { useState } from 'react';

import { enqueueQualityAudit, patchQualityIssue } from '../../api/quality';
import { Header } from '../../components/Header';
import { StatusPill } from '../../components/StatusPill';
import { useApiData } from '../../app/hooks';
import type { QualityIssue } from './types';

export function QualityIssuesView() {
  const [reload, setReload] = useState(0);
  const [status, setStatus] = useState('open');
  const [message, setMessage] = useState('');
  const { data, loading, error } = useApiData<QualityIssue[]>(`/api/quality/issues/?status=${status}&reload=${reload}`, []);
  const runAudit = async () => {
    setMessage('');
    const payload = await enqueueQualityAudit();
    setMessage(payload?.task ? '质量审计任务已加入队列。' : '质量审计任务提交失败。');
    setReload((value) => value + 1);
  };
  const updateIssue = async (issue: QualityIssue, nextStatus: QualityIssue['status']) => {
    await patchQualityIssue(issue.id, { status: nextStatus });
    setMessage(`问题 #${issue.id} 已标记为 ${nextStatus}。`);
    setReload((value) => value + 1);
  };
  return (
    <main className="page">
      <Header eyebrow="Quality" title="质量治理" description="集中查看元数据、AI 输出、复现和索引质量问题。" />
      <section className="toolbar">
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="open">待处理</option>
          <option value="acknowledged">已确认</option>
          <option value="resolved">已解决</option>
          <option value="dismissed">已忽略</option>
        </select>
        <button type="button" onClick={runAudit}>发起质量审计</button>
        {message && <span className="muted">{message}</span>}
      </section>
      {loading && <p className="muted">正在读取质量问题...</p>}
      {error && <p className="error-text">质量问题暂时无法读取。</p>}
      <section className="list-grid">
        {data.map((issue) => (
          <article className="paper-card" key={issue.id}>
            <div className="card-header">
              <div>
                <p className="eyebrow">{issue.object_type} #{issue.object_id}</p>
                <h2>{issue.dimension}</h2>
              </div>
              <StatusPill value={issue.status} />
            </div>
            <p>{issue.notes || '暂无说明。'}</p>
            <p className="muted">严重性：{issue.severity} · 分数：{issue.score ?? '未评分'}</p>
            <div className="inline-actions">
              <button type="button" className="secondary-button" onClick={() => updateIssue(issue, 'acknowledged')}>确认</button>
              <button type="button" className="secondary-button" onClick={() => updateIssue(issue, 'resolved')}>解决</button>
              <button type="button" className="secondary-button" onClick={() => updateIssue(issue, 'dismissed')}>忽略</button>
            </div>
          </article>
        ))}
        {!loading && data.length === 0 && <p className="muted">当前没有待处理质量问题。</p>}
      </section>
    </main>
  );
}
