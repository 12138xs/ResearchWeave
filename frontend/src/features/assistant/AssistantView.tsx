import { useState } from 'react';

import { createAssistantSession, sendAssistantMessage } from '../../api/assistant';
import { Header } from '../../components/Header';
import { useApiData } from '../../app/hooks';
import type { AssistantExchange, AssistantSession } from './types';

export function AssistantView() {
  const [reload, setReload] = useState(0);
  const [activeSession, setActiveSession] = useState<AssistantSession | null>(null);
  const [scopeText, setScopeText] = useState('');
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<AssistantExchange | null>(null);
  const { data: sessions } = useApiData<AssistantSession[]>(`/api/assistant/sessions/?reload=${reload}`, []);
  const createSession = async () => {
    const paperIds = scopeText
      .split(',')
      .map((item) => Number(item.trim()))
      .filter((item) => Number.isInteger(item) && item > 0);
    const payload = await createAssistantSession({
      title: paperIds.length ? `论文范围问答：${paperIds.join(', ')}` : '限定范围研究问答',
      mode: 'freeform_scoped',
      scope_json: paperIds.length ? { paper_ids: paperIds } : {}
    });
    setActiveSession(payload as AssistantSession);
    setReload((value) => value + 1);
  };
  const ask = async () => {
    if (!activeSession || !question.trim()) return;
    const payload = await sendAssistantMessage(activeSession.id, question.trim());
    setAnswer(payload as AssistantExchange);
    setQuestion('');
  };
  return (
    <main className="page">
      <Header eyebrow="Assistant" title="AI 研究助理" description="在限定论文、文档、实验或方向范围内进行有来源的研究问答。" />
      <section className="toolbar">
        <input value={scopeText} onChange={(event) => setScopeText(event.target.value)} placeholder="限定论文 ID，例如 1,2,3" />
        <button type="button" onClick={createSession}>新建限定会话</button>
        <select
          value={activeSession?.id ?? ''}
          onChange={(event) => setActiveSession(sessions.find((session) => session.id === Number(event.target.value)) ?? null)}
        >
          <option value="">选择会话</option>
          {sessions.map((session) => <option key={session.id} value={session.id}>{session.title}</option>)}
        </select>
      </section>
      <section className="detail-card">
        <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="输入一个限定范围内的问题" />
        <button type="button" onClick={ask} disabled={!activeSession || !question.trim()}>提问</button>
        {answer && (
          <article className="source-preview">
            <strong>{answer.model}</strong>
            <p>{answer.answer}</p>
            {answer.sources.length > 0 && (
              <p className="muted">来源：{answer.sources.map((source) => `${source.type}:${source.id}`).join('，')}</p>
            )}
            {answer.context_warning && <p className="muted">{answer.context_warning}</p>}
          </article>
        )}
      </section>
    </main>
  );
}
