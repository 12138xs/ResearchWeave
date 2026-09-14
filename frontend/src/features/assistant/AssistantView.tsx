import { useEffect, useRef, useState } from 'react';

import { controlAssistantExchange, startAssistantConversation, fetchAssistantSession, sendAssistantMessage } from '../../api/assistant';
import { Header } from '../../components/Header';
import { useApiData } from '../../app/hooks';
import type { AssistantExchange, AssistantSession } from './types';
import { PersonalWorkspace } from './PersonalWorkspace';
import { workspaceRequest } from '../../api/workspace';

const presets = ['根据知识库总结【方向】的研究进展，区分材料事实和待验证问题。', '判断【研究思路】是否可行，给出相关依据、主要风险和最小验证实验。', '分析【工作】的不足，比较已有方法，提出有依据的改进建议。'];
const active = (row: AssistantExchange) => ['queued', 'running'].includes(row.status);
const sourceLabels: Record<string, string> = { unclassified: '未分类来源', paper_fulltext: '论文原文', paper_abstract: '论文摘要', human_record: '人工记录', derived_research_card: '衍生整理卡', agent_summary: 'Agent 摘要', experiment_plan: '实验计划', experiment_observation: '实验观察', experiment_interpretation: '实验解释', code_reference: '代码引用' };
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
  const pending = useRef<{ session: number | null; question: string; id: string; scopeKey: string } | null>(null);
  const busyRef = useRef(false);
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
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true); setError('');
    try { await action(); } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败，请重试。'); }
    finally { busyRef.current = false; setBusy(false); }
  };
  const newTopic = () => {
    selection.current += 1; setSession(null); pending.current = null; setError(''); setConnection('');
    setScopeText(''); setScopeKind('material_ids');
  };
  const newScope = () => {
    const ids = scopeText.trim() ? scopeText.split(/[,，]/).map((item) => Number(item.trim())) : [];
    if (ids.some((id) => !Number.isInteger(id) || id <= 0) || ids.length > 100) throw new Error('高级范围请输入最多 100 个逗号分隔的正整数编号，或留空查找当前可访问知识库。');
    return ids.length ? { [scopeKind]: [...new Set(ids)] } : {};
  };
  const choose = (id: number) => perform(async () => {
    const token = ++selection.current;
    const result = await fetchAssistantSession(id);
    if (token === selection.current) {
      setSession(result); pending.current = null; setConnection('');
      const [kind, ids] = Object.entries(result.scope_json)[0] ?? ['material_ids', []];
      setScopeKind(kind); setScopeText(Array.isArray(ids) ? ids.join(',') : '');
    }
  });
  const ask = () => perform(async () => {
    if (!question.trim() || running) return;
    const text = question.trim();
    const scope = session?.scope_json ?? newScope();
    const scopeKey = JSON.stringify(scope);
    if (!pending.current || pending.current.session !== (session?.id ?? null) || pending.current.question !== text || pending.current.scopeKey !== scopeKey) {
      pending.current = { session: session?.id ?? null, question: text, id: requestId(), scopeKey };
    }
    if (session) {
      merge(await sendAssistantMessage(session.id, text, pending.current.id));
    } else {
      const result = await startAssistantConversation(text, pending.current.id, scope);
      selection.current += 1; setSession(result); setReload((value) => value + 1);
    }
    pending.current = null; setQuestion(''); setConnection('');
  });
  return <main className="page">
    <Header eyebrow="" title="科研助理" description="直接按方向提问，自动查找材料、补读依据并讨论科研思路。" />
    <details><summary>我的工作区与个人偏好</summary><PersonalWorkspace revision={workspaceRevision} /></details>
    <section className="toolbar">
      <details><summary>高级范围（可选，仅新话题生效）</summary>
      <select disabled={busy || !!session} aria-label="来源类型" value={scopeKind} onChange={(event) => setScopeKind(event.target.value)}>
        <option value="material_ids">材料编号</option><option value="paper_ids">旧论文编号</option><option value="document_ids">文档编号</option><option value="experiment_ids">实验编号</option><option value="note_ids">个人记录编号</option>
      </select>
      <input disabled={busy || !!session} aria-label="来源编号" value={scopeText} onChange={(event) => setScopeText(event.target.value)} placeholder="留空查找当前可访问知识库" />
      <p className="muted">指定范围仅用于缩小检索；追问沿用会话范围，修改请开启新话题。</p>
      </details>
      {session && <button type="button" disabled={busy} onClick={() => perform(async () => {
        if (!window.confirm('删除此会话和仍关联的 memory？已保存的实验记录会保留并解除关联。')) return;
        await workspaceRequest(`sessions/${session.id}/`, 'DELETE'); setSession(null); setReload((value) => value + 1); setWorkspaceRevision((value) => value + 1);
      })}>删除当前会话</button>}
      <button type="button" disabled={busy} onClick={newTopic}>新话题</button>
      <select aria-label="选择历史会话" disabled={busy} value={session?.id ?? ''} onChange={(event) => { if (event.target.value) void choose(Number(event.target.value)); }}>
        <option value="">选择历史会话</option>
        {sessions.map((item) => <option key={item.id} value={item.id}>{item.title} #{item.id}</option>)}
        {session && !sessions.some((item) => item.id === session.id) && <option value={session.id}>{session.title}</option>}
      </select>
    </section>
    <section className="detail-card">
      <p role="status">{session && Object.keys(session.scope_json).length ? '当前会话使用指定范围，追问沿用此范围。' : !session && scopeText.trim() ? '首问将使用高级范围。' : '当前可访问知识库：团队共享材料及本人启用的可用记录。'}</p>
      {session && Object.entries(session.scope_json).map(([kind, ids]) => <p className="muted" key={kind}>{({ material_ids: '材料', paper_ids: '旧论文', document_ids: '文档', experiment_ids: '实验', note_ids: '个人记录' } as Record<string, string>)[kind] ?? kind}：{Array.isArray(ids) ? ids.join('、') : String(ids)}</p>)}
      <p className="muted">直接提问即可，系统会自动查找相关材料并按需要补读。问题与实际读取的片段会发送至 MiniMax M3。已关联全文的旧论文可检索正文，仅有摘要的条目仍按摘要使用；公式请核对原文。</p>
      <div className="toolbar">{['研究进展', '思路可行性', '工作改进'].map((label, index) => <button type="button" key={label} disabled={busy} onClick={() => setQuestion(presets[index])}>{label}</button>)}</div>
      <textarea disabled={busy} aria-label="科研问题" maxLength={4000} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={session ? '继续追问，系统会重新查找依据' : '例如：我们库中关于复杂几何上的神经算子有哪些相关工作，分别有什么限制？'} />
      <button type="button" onClick={ask} disabled={busy || !question.trim() || !!running}>{busy ? '正在提交…' : session ? '继续提问' : '提问'}</button>
      {error && <p role="alert">{error}</p>}
      {connection && running && <p role="status">{connection}</p>}
    </section>
    {session?.exchanges.map((row) => <article className="detail-card" key={row.id}>
      <h3>{row.question}</h3>
      <p role="status">{row.progress || '历史回答'} {row.model}</p>
      {row.usage.search_calls !== undefined && <p className="muted">实际搜索 {String(row.usage.search_calls)} 次 · 读取 {String(row.usage.read_calls ?? 0)} 次 · 返回证据正文 {String(row.usage.evidence_chars ?? 0)} 字</p>}
      {row.answer && <p style={{ whiteSpace: 'pre-wrap' }}>{row.answer.split(/(\[S\d+\]|\*\*[^*]+\*\*)/g).map((part, index) => {
        const label = part.match(/^\[(S\d+)\]$/)?.[1];
        if (label && row.sources.some((source) => source.label === label)) return <a key={index} href={`#source-${row.id}-${label}`} onClick={() => {
          const detail = document.getElementById(`source-${row.id}-${label}`) as HTMLDetailsElement | null;
          if (detail) detail.open = true;
        }}>{part}</a>;
        return part.startsWith('**') ? <strong key={index}>{part.slice(2, -2)}</strong> : part;
      })}</p>}
      {row.status === 'completed' && row.answer && <button type="button" disabled={busy} onClick={() => perform(async () => {
        await workspaceRequest('workspace/entries/', 'POST', { kind: 'note', title: row.question.slice(0, 240), body: `## 科研问题\n${row.question}\n\n## Agent 回答（待核对）\n${row.answer}`, source_session: row.session, status: 'planned' });
        setWorkspaceRevision((value) => value + 1);
      })}>保存为待核对笔记</button>}
      {row.error && <p role="alert">{row.error}</p>}
      {active(row) && <button type="button" disabled={busy} onClick={() => perform(async () => merge(await controlAssistantExchange(row, 'cancel')))}>取消</button>}
      {(['failed', 'cancelled'].includes(row.status) || (active(row) && Date.now() - Date.parse(row.updated_at) > 300000)) && <button type="button" disabled={busy} onClick={() => perform(async () => merge(await controlAssistantExchange(row, 'retry')))}>重试</button>}
      {row.sources.map((source) => <details id={`source-${row.id}-${source.label}`} key={source.label}>
        <summary>[{source.label}] {source.title} · {sourceLabels[source.source_kind ?? 'unclassified'] ?? '未分类来源'} · {source.location}</summary>
        <p className="muted">{source.read_mode ? '已补读' : '检索摘录'}{source.truncated ? ' · 仅展示部分正文，不能据此认定整篇内容' : ' · 当前片段完整呈现'}</p>
        <p style={{ whiteSpace: 'pre-wrap' }}>{source.excerpt}</p>
        {source.url && <a href={source.url}>打开引用原文位置</a>}
      </details>)}
      {row.context_warning && <p className="muted">{row.context_warning}</p>}
    </article>)}
  </main>;
}
