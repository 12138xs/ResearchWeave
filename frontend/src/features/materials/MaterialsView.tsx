import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { apiFetch, payloadMessage, readResponsePayload } from '../../api/client';
import { useApiData } from '../../app/hooks';
import { Header } from '../../components/Header';

type Version = {
  id: number; number: number; filename: string; format: string; status: string;
  error: string; warnings: string[]; file_url: string;
};
type Material = { id: number; title: string; visibility: string; can_edit: boolean; versions: Version[] };
type Evidence = { id: number; ordinal: number; page: number | null; line_start: number | null; line_end: number | null; text: string; review_required: boolean };
type Detail = Version & { evidence: Evidence[]; cards: { id: number; title: string; markdown: string; evidence_ids: number[] }[] };
const emptyList = { count: 0, results: [] as Material[] };
const emptyMaterial: Material = { id: 0, title: '', visibility: '', can_edit: false, versions: [] };
const labels: Record<string, string> = { queued: '等待解析', processing: '正在解析', ready: '可用', needs_review: '待核对', failed: '解析失败' };

async function submit(url: string, data: FormData | object) {
  const response = await apiFetch(url, data instanceof FormData
    ? { method: 'POST', body: data }
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  const payload = await readResponsePayload(response);
  if (!response.ok) throw new Error(payloadMessage(payload, '操作失败，请稍后重试。'));
  return payload;
}

function Upload({ material, onComplete }: { material?: Material; onComplete: () => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [visibility, setVisibility] = useState('team');
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<string[]>([]);
  const upload = async () => {
    setBusy(true);
    setResults([]);
    for (const file of files) {
      try {
        const form = new FormData();
        form.append('file', file);
        form.append('visibility', visibility);
        const result = await submit(material ? `/api/materials/${material.id}/versions/` : '/api/materials/', form);
        setResults((old) => [...old, `${file.name}：${result.created ? '已保存' : '已存在，未重复入库'}${result.version?.status === 'failed' ? '；解析失败，可稍后重试' : ''}`]);
      } catch (error) {
        setResults((old) => [...old, `${file.name}：${error instanceof Error ? error.message : '上传失败'}`]);
      }
    }
    setBusy(false);
    onComplete();
  };
  return <section className="experiment-create-panel">
    <h2>{material ? '添加新版本' : '加入材料'}</h2>
    <p>支持 PDF、UTF-8 Markdown，每份不超过 25 MB。原文件和旧版本会保留。请勿加入涉密材料。</p>
    <label>选择文件<input type="file" accept=".pdf,.md,.markdown" multiple={!material} disabled={busy}
      onChange={(event) => setFiles(Array.from(event.target.files ?? []).slice(0, 20))} /></label>
    {!material && <label>可见范围<select value={visibility} disabled={busy} onChange={(event) => setVisibility(event.target.value)}>
      <option value="team">团队共享</option><option value="private">仅本人</option>
    </select></label>}
    <p className="muted">{material ? '新版本沿用原材料的可见范围。' : '每次最多 20 份；每份分别保存，部分失败可重新选择后上传。'}</p>
    <button type="button" disabled={busy || !files.length} onClick={upload}>{busy ? '正在保存…' : '保存材料'}</button>
    <div role="status">{results.map((text, index) => <p key={index}>{text}</p>)}</div>
  </section>;
}

export function MaterialsView() {
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const { data, loading, error } = useApiData(`/api/materials/?page=${page}&q=${encodeURIComponent(query)}&reload=${reload}`, emptyList);
  return <main className="page experiments-page">
    <Header eyebrow="" title="研究材料" description="保存原始材料、追踪版本，并查看可回到原文的证据。" />
    <Upload onComplete={() => setReload((value) => value + 1)} />
    <section className="experiment-toolbar">
      <label>按标题查找<input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} /></label>
      <button type="button" onClick={() => setReload((value) => value + 1)}>刷新解析状态</button>
    </section>
    {loading ? <p>正在读取材料…</p> : error ? <p role="alert">材料暂时无法读取，请刷新重试。</p> : <>
      <p>共 {data.count} 份材料。已有论文库与知识文档仍可从原入口访问。</p>
      {data.results.map((material) => <article className="experiment-project-row" key={material.id}>
        <Link to={`/materials/${material.id}`}>{material.title}</Link>
        <p>{material.visibility === 'private' ? '仅本人' : '团队共享'} · {material.versions.length} 个版本 · {labels[material.versions[0]?.status] ?? '等待登记'}</p>
      </article>)}
      <div className="inline-actions">
        <button type="button" disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</button>
        <span>第 {page} 页</span>
        <button type="button" disabled={page * 25 >= data.count} onClick={() => setPage(page + 1)}>下一页</button>
      </div>
    </>}
  </main>;
}

function VersionEvidence({ material, version, reload, refresh }: { material: Material; version: Version; reload: number; refresh: () => void }) {
  const { data, loading, error } = useApiData<Detail | null>(`/api/materials/${material.id}/versions/${version.id}/?reload=${reload}`, null);
  const [message, setMessage] = useState('');
  const [title, setTitle] = useState('');
  const [markdown, setMarkdown] = useState('');
  const [evidenceIds, setEvidenceIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const mutate = async (action: 'retry' | 'cards') => {
    setBusy(true);
    setMessage('');
    try {
      const response = await submit(`/api/materials/${material.id}/versions/${version.id}/${action}/`,
        action === 'cards' ? { title, markdown, evidence_ids: evidenceIds } : {});
      setMessage(action === 'cards' ? '研究卡片已保存，作为衍生记录保留。' : response.detail);
      refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '操作失败。');
    } finally {
      setBusy(false);
    }
  };
  if (loading) return <p>正在读取版本证据…</p>;
  if (error || !data) return <p role="alert">证据暂时无法读取，请刷新重试。</p>;
  return <section>
    <h2>版本 {data.number} · {labels[data.status]}</h2>
    <a href={data.file_url} target="_blank" rel="noreferrer">打开此版本原文件：{data.filename}</a>
    {data.warnings.map((warning) => <p key={warning}>{warning}</p>)}
    {data.error && <p role="alert">{data.error}</p>}
    {material.can_edit && ['failed', 'queued', 'processing'].includes(data.status) &&
      <button type="button" disabled={busy} onClick={() => mutate('retry')}>重试解析（等待中的任务满 5 分钟后可重试）</button>}
    {data.evidence.map((evidence) => <article className="experiment-project-row" id={`evidence-${evidence.id}`} key={evidence.id}>
      <h3>{evidence.page ? `第 ${evidence.page} 页` : `第 ${evidence.line_start}–${evidence.line_end} 行`}</h3>
      <p>{evidence.review_required ? '待核对原文' : '已提取文本'} · 证据 {evidence.id}</p>
      {evidence.page && <a href={`${data.file_url}#page=${evidence.page}`} target="_blank" rel="noreferrer">打开原文此页</a>}
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{evidence.text || '本页未提取到文字，请查看原文件。'}</pre>
      {material.can_edit && <label><input type="checkbox" checked={evidenceIds.includes(evidence.id)} onChange={(event) =>
        setEvidenceIds((old) => event.target.checked ? [...old, evidence.id] : old.filter((id) => id !== evidence.id))} />引用到研究卡片</label>}
    </article>)}
    {material.can_edit && data.evidence.length > 0 && <section className="experiment-create-panel">
      <h2>导入研究卡片</h2>
      <p>粘贴整理好的 Markdown，并勾选上方依据。卡片属于衍生解读，不能替代原文。</p>
      <label>标题<input maxLength={300} value={title} onChange={(event) => setTitle(event.target.value)} /></label>
      <label>Markdown 正文<textarea rows={8} maxLength={100000} value={markdown} onChange={(event) => setMarkdown(event.target.value)} /></label>
      <button type="button" disabled={busy || !title.trim() || !markdown.trim() || !evidenceIds.length} onClick={() => mutate('cards')}>保存卡片</button>
    </section>}
    <p role="status">{message}</p>
    {data.cards.map((card) => <article className="experiment-project-row" key={card.id}>
      <h3>{card.title} · 衍生记录</h3>
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{card.markdown}</pre>
      <p>引用：{card.evidence_ids.map((id) => <a key={id} href={`#evidence-${id}`}> 证据 {id} </a>)}</p>
    </article>)}
  </section>;
}

export function MaterialDetailView() {
  const { id } = useParams();
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const { data, loading, error } = useApiData<Material>(`/api/materials/${id}/?reload=${reload}`, emptyMaterial);
  const refresh = () => setReload((value) => value + 1);
  const version = data.versions.find((item) => item.id === selected) ?? data.versions[0];
  return <main className="page experiments-page">
    <Link to="/materials">返回研究材料</Link>
    <Header eyebrow="" title={loading ? '正在读取材料…' : error ? '材料不可用' : data.title} description="每条证据绑定原文件版本，更新材料不会改变旧引用。" />
    {error && <p role="alert">材料不存在、无权访问或读取失败。</p>}
    {!loading && !error && <>
      {data.can_edit && <Upload material={data} onComplete={refresh} />}
      <div className="inline-actions">
        <label>原文件版本<select value={version?.id ?? ''} onChange={(event) => setSelected(Number(event.target.value))}>
          {data.versions.map((item) => <option key={item.id} value={item.id}>版本 {item.number} · {labels[item.status]}</option>)}
        </select></label>
        <button type="button" onClick={refresh}>刷新状态</button>
      </div>
      {version && <VersionEvidence key={version.id} material={data} version={version} reload={reload} refresh={refresh} />}
    </>}
  </main>;
}
