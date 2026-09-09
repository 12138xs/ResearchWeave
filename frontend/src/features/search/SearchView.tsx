import { Link, useSearchParams } from 'react-router-dom';
import { useMemo, useState } from 'react';

import { enqueueSearchReindex } from '../../api/search';
import { Header } from '../../components/Header';
import { useApiData } from '../../app/hooks';
import type { SearchResponse } from './types';
import { EvidenceResults } from './EvidenceResults';

const emptySearch: SearchResponse = {
  count: 0,
  next: null,
  previous: null,
  results: []
};

const typeLabels: Record<string, string> = {
  paper: '论文',
  document: '文档',
  experiment: '实验'
};

export function SearchView() {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get('q') ?? '');
  const [message, setMessage] = useState('');
  const searchUrl = useMemo(() => params.get('scope') === 'materials' ? '' : `/api/search/?${new URLSearchParams(params).toString()}`, [params]);
  const { data, loading, error } = useApiData<SearchResponse>(searchUrl, emptySearch);
  const submit = () => {
    const next = new URLSearchParams(params);
    if (query.trim()) next.set('q', query.trim());
    else next.delete('q');
    setParams(next);
  };
  const reindex = async () => {
    setMessage('');
    const payload = await enqueueSearchReindex();
    setMessage(payload?.task ? `重建索引任务已加入队列，可在任务页查看：T${String(payload.task.id).padStart(4, '0')}` : '重建索引任务提交失败。');
  };
  return (
    <main className="page search-page">
      <Header eyebrow="" title="统一检索" description="查找材料原文证据，以及已有论文、文档和复现实验。" />
      <section className="search-command-panel">
        <div className="search-command-main">
          <label>
            <span>检索内容</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') submit();
              }}
              placeholder="搜索论文、文档、实验、关键词或研究问题"
            />
          </label>
          <label>
            <span>范围</span>
            <select
              value={params.get('scope') ?? ''}
              onChange={(event) => {
                const next = new URLSearchParams(params);
                if (event.target.value) next.set('scope', event.target.value);
                else next.delete('scope');
                setParams(next);
              }}
            >
              <option value="">全部内容</option>
              <option value="materials">研究材料原文</option>
              <option value="paper">论文</option>
              <option value="document">文档</option>
              <option value="experiment">实验</option>
            </select>
          </label>
          <button type="button" onClick={submit}>检索</button>
          {params.get('scope') !== 'materials' && <button type="button" className="secondary-button" onClick={reindex}>重建旧资料索引</button>}
        </div>
        {(data.count > 0 || params.get('q') || message) && <div className="search-command-meta">
          <span>{params.get('scope') === 'materials' ? '材料证据直接读取，无需重建旧资料索引' : data.count ? `旧资料找到 ${data.count} 条结果` : '旧资料暂无匹配结果'}</span>
          {message && <strong>{message} <Link to="/tasks">打开任务队列</Link></strong>}
        </div>}
      </section>
      {(!params.get('scope') || params.get('scope') === 'materials') && <EvidenceResults key={params.get('q') ?? ''} query={params.get('q') ?? ''} />}
      {loading && <p className="muted">正在检索...</p>}
      {error && <p className="error-text">检索服务暂时不可用。</p>}
      {params.get('scope') !== 'materials' && <section className="search-results" aria-label="旧资料检索结果">
        {data.results.map((entry) => (
          <article className="search-result-row" key={`${entry.object_type}-${entry.object_id}`}>
            <div className="search-result-type">{typeLabels[entry.object_type] ?? entry.object_type}</div>
            <div className="search-result-content">
              <h2><Link to={entry.url}>{entry.title}</Link></h2>
              <p>{entry.summary || '暂无摘要。'}</p>
            </div>
            {entry.keywords_json.length > 0 && <div className="tag-cloud">
              {entry.keywords_json.slice(0, 6).map((keyword) => <span key={keyword}>{keyword}</span>)}
            </div>}
            <Link className="secondary-button link-button" to={entry.url}>打开</Link>
          </article>
        ))}
        {!loading && data.results.length === 0 && (
          <article className="search-empty-state">
            <h2>{params.get('q') ? '暂无检索结果' : '索引可能尚未建立'}</h2>
            <p>{params.get('q') ? '换一个关键词，或重建索引后再试。' : '首次使用前可先重建索引。'}</p>
            <div className="inline-actions">
              <button type="button" className="secondary-button" onClick={reindex}>重建索引</button>
              <Link className="secondary-button link-button" to="/tasks">查看任务</Link>
            </div>
          </article>
        )}
      </section>}
    </main>
  );
}
