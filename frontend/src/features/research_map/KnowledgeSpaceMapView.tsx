import { Link, useParams } from 'react-router-dom';
import { useState } from 'react';

import { enqueueKnowledgeSpaceMap } from '../../api/researchMap';
import { Header } from '../../components/Header';
import { useApiData } from '../../app/hooks';
import type { ResearchMapPayload } from './types';

const emptyMap: ResearchMapPayload = {
  root: {},
  children: [],
  relations: [],
  snapshot: null
};

export function KnowledgeSpaceMapView() {
  const { id } = useParams();
  const [reload, setReload] = useState(0);
  const [message, setMessage] = useState('');
  const spaceId = Number(id);
  const { data, loading, error } = useApiData<ResearchMapPayload>(
    Number.isInteger(spaceId) ? `/api/knowledge-spaces/${spaceId}/map/?reload=${reload}` : '',
    emptyMap
  );
  const rootName = String(data.root.name ?? '知识空间');
  const generate = async () => {
    if (!Number.isInteger(spaceId)) return;
    const payload = await enqueueKnowledgeSpaceMap(spaceId);
    setMessage(payload?.task ? `方向地图生成任务已加入队列：T${String(payload.task.id).padStart(4, '0')}` : '方向地图任务提交失败。');
    setReload((value) => value + 1);
  };
  return (
    <main className="page">
      <Header eyebrow="Research Map" title={rootName} description="查看方向节点、子方向、关联方向和内容规模。" />
      <section className="toolbar">
        <button type="button" onClick={generate}>生成地图快照</button>
        <Link className="secondary-button link-button" to="/tasks">任务队列</Link>
        {message && <span className="muted">{message}</span>}
      </section>
      {loading && <p className="muted">正在读取方向地图...</p>}
      {error && <p className="error-text">方向地图暂时无法读取。</p>}
      <section className="detail-grid">
        <article className="detail-card">
          <h2>内容摘要</h2>
          <div className="metadata-grid">
            <span>论文</span><strong>{String(data.root.paper_count ?? 0)}</strong>
            <span>文档</span><strong>{String(data.root.document_count ?? 0)}</strong>
            <span>实验</span><strong>{String(data.root.experiment_count ?? 0)}</strong>
            <span>待处理质量问题</span><strong>{String(data.root.open_quality_issue_count ?? 0)}</strong>
          </div>
        </article>
        <article className="detail-card">
          <h2>最新快照</h2>
          {data.snapshot ? (
            <p>v{String(data.snapshot.version ?? '?')} · {String(data.snapshot.generator ?? 'unknown')}</p>
          ) : (
            <p className="muted">尚未生成快照。</p>
          )}
        </article>
      </section>
      <section className="list-grid">
        {data.children.map((child) => (
          <article className="paper-card" key={String(child.id)}>
            <p className="eyebrow">子方向</p>
            <h2>{String(child.name ?? '未命名')}</h2>
            <p>{String(child.description ?? '') || '暂无描述。'}</p>
          </article>
        ))}
        {data.relations.map((relation) => (
          <article className="paper-card" key={String(relation.id)}>
            <p className="eyebrow">关联方向</p>
            <h2>{String(relation.source_name)} → {String(relation.target_name)}</h2>
            <p>{String(relation.relation_type)} · 权重 {String(relation.weight ?? '')}</p>
          </article>
        ))}
      </section>
    </main>
  );
}
