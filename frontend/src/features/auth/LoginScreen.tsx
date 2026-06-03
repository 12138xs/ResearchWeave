import { type FormEvent, useState } from 'react';

import { apiFetch, payloadMessage, readResponsePayload } from '../../api/client';
import { useHealth } from '../../app/hooks';
import { StatusPill } from '../../components/StatusPill';
import type { AuthSession } from './types';

export function LoginScreen({ onLogin }: { onLogin: (session: AuthSession) => void }) {
  const health = useHealth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  async function submitLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      const response = await apiFetch('/api/auth/login/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '登录失败，请检查用户名和密码。'));
      onLogin(payload as AuthSession);
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败，请稍后重试。');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-panel">
        <div className="login-brand">
          <span>A510 知识库</span>
          <h1>研究知识工作台</h1>
          <p>使用团队账号进入论文库、知识文档、跨论文分析和任务队列。</p>
        </div>
        <form className="login-form" onSubmit={submitLogin}>
          <label>
            <span>用户名</span>
            <input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} />
          </label>
          <label>
            <span>密码</span>
            <input
              autoComplete="current-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <button type="submit" disabled={submitting || !username.trim() || !password}>
            {submitting ? '正在登录' : '登录'}
          </button>
          {error && <div className="form-message form-message-error">{error}</div>}
        </form>
        <div className="login-health">
          <StatusPill value={health.status} />
          <span>API / Postgres / Redis</span>
        </div>
      </section>
    </main>
  );
}
