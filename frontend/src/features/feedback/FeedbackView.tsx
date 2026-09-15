import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch, payloadMessage, readResponsePayload } from '../../api/client';
import { Header } from '../../components/Header';
import './feedback.css';

type Feature = { key: string; label: string; path: string };
type Feedback = { id: number; author_name: string; content: string; features: string[]; created_at: string };
type Feed = { count: number; page: number; page_size: number; catalog: Feature[]; results: Feedback[] };

// crypto.randomUUID is unavailable on some HTTP intranet origins.
function requestId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function FeedbackView() {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [content, setContent] = useState('');
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [notice, setNotice] = useState('');
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [mentionOpen, setMentionOpen] = useState(false);
  const busy = useRef(false);
  const pending = useRef<{ content: string; id: string } | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    apiFetch(`/api/feedback/?page=${page}`).then(async (response) => {
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '意见列表加载失败。'));
      if (active) { setFeed(payload as Feed); setLoadError(''); }
    }).catch((reason: unknown) => {
      if (active) setLoadError(reason instanceof Error ? reason.message : '意见列表加载失败。');
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [page, revision]);

  function mention(feature: Feature) {
    const cursor = textarea.current?.selectionStart ?? content.length;
    const before = content.slice(0, cursor).replace(/(^|\s)@[^\s@]*$/, '$1');
    const inserted = `${before}${before && !/\s$/.test(before) ? ' ' : ''}@${feature.label} `;
    const next = inserted + content.slice(cursor);
    if (next.length > 4000) { setError('意见最多 4000 字，请先缩短内容。'); return; }
    setContent(next); setMentionOpen(false); setNotice('');
    requestAnimationFrame(() => { textarea.current?.focus(); textarea.current?.setSelectionRange(inserted.length, inserted.length); });
  }

  async function submit() {
    const text = content.trim();
    if (!text || busy.current) return;
    busy.current = true; setSending(true); setError(''); setNotice('');
    try {
      if (pending.current?.content !== text) pending.current = { content: text, id: requestId() };
      const response = await apiFetch('/api/feedback/', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text, request_id: pending.current.id })
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '提交失败，请重试。'));
      setContent(''); pending.current = null; setMentionOpen(false);
      setNotice('意见已记录，全组成员可查看。'); setPage(1); setRevision((value) => value + 1);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '提交失败，请重试。'); }
    finally { busy.current = false; setSending(false); }
  }

  return <div className="feedback-page">
    <Header eyebrow="运行管理" title="意见箱" description="把使用中的问题与改进建议留在这里，一起完善实验室的科研工具。" />
    <section className="feedback-compose" aria-label="提交改进意见">
      <div className="feedback-heading"><h2>提出改进意见</h2><span>全组可见 · 自动记录提交人与时间</span></div>
      <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <label htmlFor="feedback-content">你的意见</label>
        <textarea id="feedback-content" ref={textarea} rows={5} maxLength={4000} value={content} disabled={sending}
          placeholder="例如：@内置科研Agent 希望回答后能按论文展示引用的章节。可以描述遇到的问题、预期效果或改进想法。"
          onChange={(event) => {
            setContent(event.target.value); setNotice('');
            setMentionOpen(/(^|\s)@[^\s@]*$/.test(event.target.value.slice(0, event.target.selectionStart)));
          }} onKeyDown={(event) => { if (event.key === 'Escape') setMentionOpen(false); }} />
        <div className="feedback-actions">
          <button type="button" className="secondary" aria-expanded={mentionOpen} aria-controls="feedback-features"
            disabled={sending || !feed} onClick={() => setMentionOpen(!mentionOpen)}>@ 关联功能</button>
          <span className="feedback-count">{content.length} / 4000</span>
          <button type="submit" disabled={sending || !content.trim()}>{sending ? '正在提交…' : '提交意见'}</button>
        </div>
        {mentionOpen && <div id="feedback-features" className="feedback-features" aria-label="可关联的功能">
          <p>选择功能插入 @ 标记，可关联多个功能；不会发送通知。</p>
          <div>{feed?.catalog.map((feature) => <button type="button" className="secondary" key={feature.key} onClick={() => mention(feature)}>@{feature.label}</button>)}</div>
        </div>}
        {error && <p role="alert" className="feedback-error">{error}</p>}
        {notice && <p role="status" className="feedback-notice">{notice}</p>}
      </form>
    </section>
    <section className="feedback-list" aria-label="团队改进意见" aria-busy={loading}>
      <div className="feedback-heading"><h2>团队意见{feed ? ` · ${feed.count}` : ''}</h2><button type="button" className="secondary" disabled={loading} onClick={() => setRevision((value) => value + 1)}>刷新</button></div>
      {loadError ? <p role="alert" className="feedback-error">{loadError}</p> : loading ? <p>正在加载意见…</p> : !feed?.results.length ? <div className="feedback-empty">还没有意见。欢迎记录第一条建议。</div> : feed.results.map((item) => <article className="feedback-item" key={item.id}>
        <div className="feedback-meta"><strong>{item.author_name}</strong><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString('zh-CN', { hour12: false })}</time><span>#{item.id}</span></div>
        <p className="feedback-content">{item.content}</p>
        {!!item.features.length && <div className="feedback-tags">{item.features.map((key) => {
          const feature = feed.catalog.find((entry) => entry.key === key);
          return feature ? <Link key={key} to={feature.path}>@{feature.label}</Link> : null;
        })}</div>}
      </article>)}
      {feed && feed.count > feed.page_size && <nav className="feedback-pagination" aria-label="意见分页">
        <button className="secondary" disabled={loading || page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
        <span>第 {page} / {Math.ceil(feed.count / feed.page_size)} 页</span>
        <button className="secondary" disabled={loading || page * feed.page_size >= feed.count} onClick={() => setPage(page + 1)}>下一页</button>
      </nav>}
    </section>
  </div>;
}
