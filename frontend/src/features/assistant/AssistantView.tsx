import { useEffect, useRef, useState } from 'react';

import { controlAssistantExchange, createAssistantSession, fetchAssistantSession, sendAssistantMessage } from '../../api/assistant';
import { Header } from '../../components/Header';
import { useApiData } from '../../app/hooks';
import type { AssistantExchange, AssistantSession } from './types';
import { PersonalWorkspace } from './PersonalWorkspace';
import { workspaceRequest } from '../../api/workspace';

const presets = ['根据知识库总结【方向】的研究进展，区分材料事实和待验证问题。', '判断【研究思路】是否可行，给出相关依据、主要风险和最小验证实验。', '分析【工作】的不足，比较已有方法，提出有依据的改进建议。'];
const active = (row: AssistantExchange) => ['queued', 'running'].includes(row.status);
// crypto.randomUUID requires a secure context; this app also supports an internal HTTP entry.
function requestId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function AssistantView() {
  const [workspaceRevision, setWorkspaceRevision] = useState(0);
  const [reload, setReload] = useState(0);
  const [session, setSession] = useState<AssistantSession | null>(null);
  const [scopeText, setScopeText] = useState('');
  const [scopeKind, setScopeKind] = useState('material_ids');
  const [question, setQuestion] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [connection, setConnection] = useState('');
  const pending = useRef<{ session: number; question: string; id: string } | null>(null);
  const selection = useRef(0);
  const { data: sessions } = useApiData<AssistantSession[]>(`/api/assistant/sessions/?reload=${reload}`, []);
  const running = session?.exchanges.find(active);
  const merge = (row: AssistantExchange) => setSession((current) => current?.id === row.session
    ? { ...current, exchanges: [...current.exchanges.filter((item) => item.id !== row.id), row].sort((a, b) => a.id - b.id) } : current);

  useEffect(() => {
    if (!running) return;
    const stream = new EventSource(`/api/assistant/sessions/${running.session}/exchanges/${running.id}/progress/`);
    stream.addEventListener('progress', (event) => {
      const row = JSON.parse((event as MessageEvent).data) as AssistantExchange;
      merge(row);
      setConnection('');
      if (!active(row)) stream.close();
    });
    stream.onerror = () => setConnection('正在等待下一次进度更新；自动重连不会重复提交问题。');
    return () => stream.close();
  }, [running?.id, running?.attempt, running?.session]);

  const perform = async (action: () => Promise<void>) => {
    setBusy(true); setError('');
    try { await action(); } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败，请重试。'); }
    finally { setBusy(false); }
  };
  const create = () => perform(async () => {
    const ids = scopeText.trim() ? scopeText.split(/[,，]/).map((item) => Number(item.trim())) : [];
    if (ids.some((id) => !Number.isInteger(id) || id <= 0)) throw new Error('请输入逗号分隔的正整数编号。');
    const result = await createAssistantSession({ title: ids.length ? '指定材料研究会话' : '知识库研究会话', mode: 'freeform_scoped', scope_json: ids.length ? { [scopeKind]: ids } : {} });
    selection.current += 1; setSession(result); setReload((value) => value + 1); pending.current = null;
  });
  const choose = (id: number) => perform(async () => {
    const token = ++selection.current;
    const result = await fetchAssistantSession(id);
    if (token === selection.current) { setSession(result); pending.current = null; setConnection(''); }
  });
  const ask = () => perform(async () => {
    if (!session || !question.trim()) return;
    const text = question.trim();
    if (!pending.current || pending.current.session !== session.id || pending.current.question !== text) {
      pending.current = { session: session.id, question: text, id: requestId() };
    }
    const row = await sendAssistantMessage(session.id, text, pending.current.id);
    merge(row); pending.current = null; setQuestion(''); setConnection('');
  });
  return <main className="page">
    <Header eyebrow="Research assistant" title="科研助理" description="根据授权知识库查找依据、比较工作、讨论科研思路。" />
    <PersonalWorkspace revision={workspaceRevision} />
    <section className="toolbar">
      <select aria-label="来源类型" value={scopeKind} onChange={(event) => setScopeKind(event.target.value)}>
        <option value="material_ids">材料编号</option><option value="paper_ids">旧论文编号</option><option value="document_ids">文档编号</option><option value="experiment_ids">实验编号</option><option value="note_ids">个人记录编号</option>
      </select>
      {session && <button type="button" disabled={busy} onClick={() => perform(async () => {
        if (!window.confirm('删除此会话和仍关联的 memory？已保存的实验记录会保留并解除关联。')) return;
        await workspaceRequest(`sessions/${session.id}/`, 'DELETE'); setSession(null); setReload((value) => value + 1); setWorkspaceRevision((value) => value + 1);
      })}>删除当前会话</button>}
      <input aria-label="来源编号" value={scopeText} onChange={(event) => setScopeText(event.target.value)} placeholder="可选：编号用逗号分隔；留空查全部授权材料" />
      <button type="button" disabled={busy} onClick={create}>新建会话</button>
      <select aria-label="选择历史会话" disabled={busy} value={session?.id ?? ''} onChange={(event) => { if (event.target.value) void choose(Number(event.target.value)); }}>
        <option value="">选择历史会话</option>
        {sessions.map((item) => <option key={item.id} value={item.id}>{item.title} #{item.id}</option>)}
        {session && !sessions.some((item) => item.id === session.id) && <option value={session.id}>{session.title}</option>}
      </select>
    </section>
    <section className="detail-card">
      <p className="muted">提问会将问题和可见摘录发送至 MiniMax M3，消耗现有接口额度。依据仅限检索到的材料；旧论文目前读取摘要，公式请核对原文。</p>
      <div className="toolbar">{['研究进展', '思路可行性', '工作改进'].map((label, index) => <button type="button" key={label} onClick={() => setQuestion(presets[index])}>{label}</button>)}</div>
      <textarea aria-label="科研问题" maxLength={4000} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="填写主题、思路或具体工作后提问" />
      <button type="button" onClick={ask} disabled={busy || !session || !question.trim() || !!running}>提问</button>
      {error && <p role="alert">{error}</p>}
      {connection && running && <p role="status">{connection}</p>}
    </section>
    {session?.exchanges.map((row) => <article className="detail-card" key={row.id}>
      <h3>{row.question}</h3>
      <p role="status">{row.progress || '历史回答'} {row.model}</p>
      {row.answer && <p style={{ whiteSpace: 'pre-wrap' }}>{row.answer}</p>}
      {row.status === 'completed' && row.answer && <button type="button" disabled={busy} onClick={() => perform(async () => {
        await workspaceRequest('workspace/entries/', 'POST', { kind: 'note', title: row.question.slice(0, 240), body: `## 科研问题\n${row.question}\n\n## Agent 回答（待核对）\n${row.answer}`, source_session: row.session, status: 'observed' });
        setWorkspaceRevision((value) => value + 1);
      })}>保存到我的记录</button>}
      {row.error && <p role="alert">{row.error}</p>}
      {active(row) && <button type="button" disabled={busy} onClick={() => perform(async () => merge(await controlAssistantExchange(row, 'cancel')))}>取消</button>}
      {(['failed', 'cancelled'].includes(row.status) || (active(row) && Date.now() - Date.parse(row.updated_at) > 300000)) && <button type="button" disabled={busy} onClick={() => perform(async () => merge(await controlAssistantExchange(row, 'retry')))}>重试</button>}
      {row.sources.map((source) => <details key={source.label}>
        <summary>[{source.label}] {source.title} · {source.location}</summary>
        <p style={{ whiteSpace: 'pre-wrap' }}>{source.excerpt}</p>
        {source.url && <a href={source.url}>打开引用原文位置</a>}
        <p className="muted">引用内容指纹：{source.sha256}</p>
      </details>)}
      {row.context_warning && <p className="muted">{row.context_warning}</p>}
    </article>)}
  </main>;
}
