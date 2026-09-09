import { useEffect, useRef, useState } from 'react';
import { newRequestId, workspaceRequest } from '../../api/workspace';
import type { PersonalEntry, PersonalProfile, Publication } from '../../api/workspace';

const template = `## 日期\n\n## 研究问题与假设\n\n## 关联论文 / 代码与数据版本\n\n## 配置与运行条件\n\n## 观察与指标\n\n## 解释（与观察区分）\n\n## 下一步与失败判据\n`;

export function PersonalWorkspace({ revision }: { revision: number }) {
  const [profile, setProfile] = useState<PersonalProfile>({ style: '', memory_enabled: true });
  const [entries, setEntries] = useState<PersonalEntry[]>([]);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [editing, setEditing] = useState<PersonalEntry | null>(null);
  const [kind, setKind] = useState<'memory' | 'note'>('note');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState(template);
  const [status, setStatus] = useState<PersonalEntry['status']>('planned');
  const [source, setSource] = useState('');
  const [sharing, setSharing] = useState<PersonalEntry | null>(null);
  const [sharedTitle, setSharedTitle] = useState('');
  const [sharedBody, setSharedBody] = useState('');
  const [evidence, setEvidence] = useState('');
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const pendingPublication = useRef<{ key: string; id: string } | null>(null);
  const profileLoaded = useRef(false);

  const refreshEntries = async () => setEntries(await workspaceRequest<PersonalEntry[]>('workspace/entries/'));
  const refreshPublications = async () => setPublications(await workspaceRequest<Publication[]>('publications/'));
  useEffect(() => {
    let cancelled = false;
    Promise.all([workspaceRequest<PersonalProfile>('workspace/profile/'), workspaceRequest<PersonalEntry[]>('workspace/entries/'), workspaceRequest<Publication[]>('publications/')])
      .then(([p, e, shares]) => { if (!cancelled) {
        if (!profileLoaded.current) { setProfile(p); profileLoaded.current = true; }
        setEntries(e); setPublications(shares);
      } })
      .catch((reason: unknown) => { if (!cancelled) setMessage(reason instanceof Error ? reason.message : '加载失败'); });
    return () => { cancelled = true; };
  }, [revision]);
  const perform = async (action: () => Promise<void>) => {
    setBusy(true); setMessage('');
    try { await action(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : '操作失败'); }
    finally { setBusy(false); }
  };
  const edit = (entry: PersonalEntry) => {
    setEditing(entry); setKind(entry.kind); setTitle(entry.title); setBody(entry.body); setStatus(entry.status); setSource(entry.source_session ? String(entry.source_session) : '');
  };
  const reset = (value: 'note' | 'memory') => { setEditing(null); setKind(value); setTitle(''); setBody(value === 'note' ? template : ''); setSource(''); setStatus('planned'); };
  const save = () => perform(async () => {
    const sourceId = source.trim() ? Number(source.trim()) : null;
    if (sourceId !== null && (!Number.isInteger(sourceId) || sourceId <= 0)) throw new Error('来源会话编号必须是正整数。');
    await workspaceRequest(`workspace/entries/${editing ? `${editing.id}/` : ''}`, editing ? 'PATCH' : 'POST', {
      kind, title, body, status, source_session: sourceId,
    });
    await refreshEntries(); reset(kind); setMessage('已保存到个人工作区。');
  });
  const publish = () => perform(async () => {
    if (!sharing) return;
    const ids = evidence.trim() ? evidence.split(/[,，]/).map((value) => Number(value.trim())) : [];
    if (ids.some((id) => !Number.isInteger(id) || id < 1)) throw new Error('证据编号必须是逗号分隔的正整数。');
    const payload = { title: sharedTitle, body: sharedBody, evidence_ids: ids, reviewed };
    const key = JSON.stringify([sharing.id, payload]);
    if (pendingPublication.current?.key !== key) pendingPublication.current = { key, id: newRequestId() };
    await workspaceRequest(`workspace/entries/${sharing.id}/publish/`, 'POST', { ...payload, request_id: pendingPublication.current.id });
    pendingPublication.current = null; setSharing(null); await refreshPublications(); setMessage('独立共享版本已发布，个人原稿保持私密。');
  });
  return <details className="detail-card">
    <summary>个人研究工作区 · 风格、memory 与实验记录</summary>
    <p className="muted">仅本人可管理。启用的个人背景会随提问发送给模型，但不能作为论文证据；只记录你明确保存的内容。</p>
    {message && <p role="status">{message}</p>}
    <h3>Agent 风格</h3>
    <textarea aria-label="个人 Agent 风格" maxLength={2000} value={profile.style} onChange={(event) => setProfile({ ...profile, style: event.target.value })} placeholder="例如：先解释 AI 基础概念，再讨论数学假设与实验验证。" />
    <label><input type="checkbox" checked={profile.memory_enabled} onChange={(event) => setProfile({ ...profile, memory_enabled: event.target.checked })} />在回答中使用已启用 memory</label>
    <button type="button" disabled={busy} onClick={() => perform(async () => { setProfile(await workspaceRequest<PersonalProfile>('workspace/profile/', 'PATCH', profile)); setMessage('个人设置已保存，新问题按新设置执行。'); })}>保存设置</button>
    <p><a href="/api/assistant/workspace/export/">导出整个工作区</a> · <a href="/api/assistant/workspace/export/?section=style">风格 Markdown</a> · <a href="/api/assistant/workspace/export/?section=memory">Memory Markdown</a></p>
    <div className="toolbar"><button type="button" onClick={() => reset('note')}>新实验记录</button><button type="button" onClick={() => reset('memory')}>新增 memory</button></div>
    <h3>{editing ? '编辑' : '新建'}{kind === 'note' ? '实验记录' : '个人记忆'}</h3>
    <input aria-label="记录标题" maxLength={240} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="标题" />
    <textarea aria-label="记录正文" maxLength={kind === 'memory' ? 500 : 12000} value={body} onChange={(event) => setBody(event.target.value)} />
    {kind === 'note' && <select aria-label="记录阶段" value={status} onChange={(event) => setStatus(event.target.value as PersonalEntry['status'])}><option value="planned">计划</option><option value="observed">观察</option><option value="concluded">结论</option></select>}
    <input aria-label="来源会话" value={source} onChange={(event) => setSource(event.target.value)} placeholder="可选：本人来源会话编号；清空表示解除关联" />
    <p className="muted">删除来源会话时，关联 memory 会一并删除；解除关联后保留。删除 memory 停止后续使用，不自动删除已保存日志或历史回答。</p>
    <button type="button" disabled={busy || !title.trim() || !body.trim()} onClick={save}>保存个人记录</button>
    {entries.map((entry) => <article className="source-preview" key={entry.id}>
      <strong>{entry.kind === 'memory' ? 'Memory' : '实验记录'} #{entry.id} · {entry.title}</strong>
      <p className="muted">{entry.enabled ? '启用' : '停用'} · {entry.updated_at} · 来源会话 {entry.source_session ?? '手动'}</p>
      <details><summary>查看正文</summary><p style={{ whiteSpace: 'pre-wrap' }}>{entry.body}</p></details>
      <button type="button" disabled={busy} onClick={() => edit(entry)}>编辑</button>
      <button type="button" disabled={busy} onClick={() => perform(async () => { await workspaceRequest(`workspace/entries/${entry.id}/`, 'PATCH', { enabled: !entry.enabled }); await refreshEntries(); })}>{entry.enabled ? '停用' : '启用'}</button>
      <button type="button" disabled={busy} onClick={() => perform(async () => { await workspaceRequest(`workspace/entries/${entry.id}/`, 'DELETE'); await refreshEntries(); if (editing?.id === entry.id) reset(kind); })}>删除</button>
      {entry.kind === 'note' && <button type="button" disabled={busy} onClick={() => { setSharing(entry); setSharedTitle(''); setSharedBody(''); setEvidence(''); setReviewed(false); }}>整理共享版本</button>}
    </article>)}
    {sharing && <section className="detail-card">
      <h3>整理独立共享版本</h3>
      <p>仅发布下面明确填写的正文和共享证据；请自行去除私密信息。不会复制原记录、会话或 memory。</p>
      <input aria-label="共享标题" maxLength={240} value={sharedTitle} onChange={(event) => setSharedTitle(event.target.value)} placeholder="共享标题" />
      <textarea aria-label="共享正文" maxLength={12000} value={sharedBody} onChange={(event) => setSharedBody(event.target.value)} placeholder="填入已核对、可全组查看的正文" />
      <input aria-label="共享证据编号" value={evidence} onChange={(event) => setEvidence(event.target.value)} placeholder="可选：团队共享材料的证据编号，逗号分隔" />
      <label><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} />已核对正文与来源可向全组共享</label>
      <button type="button" disabled={busy || !reviewed || !sharedTitle.trim() || !sharedBody.trim()} onClick={publish}>发布共享版本</button>
      <button type="button" onClick={() => setSharing(null)}>取消整理</button>
    </section>}
    <h3>团队已发布研究记录</h3>
    <p className="muted">显示最近 200 条。引用的共享材料撤回后，对应发布内容将隐藏。</p>
    {publications.map((item) => <details key={item.id}>
      <summary>{item.title}</summary><p style={{ whiteSpace: 'pre-wrap' }}>{item.body}</p>
      <p>原文证据编号：{item.evidence_ids.join(', ') || '未附加'}</p>
      {item.can_delete && <button type="button" disabled={busy} onClick={() => perform(async () => { await workspaceRequest(`publications/${item.id}/`, 'DELETE'); await refreshPublications(); })}>撤回共享版本</button>}
    </details>)}
  </details>;
}
