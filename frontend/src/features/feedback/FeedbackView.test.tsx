import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { FeedbackView } from './FeedbackView';
import { apiFetch } from '../../api/client';

vi.mock('../../api/client', async (original) => ({ ...await original<typeof import('../../api/client')>(), apiFetch: vi.fn() }));
let host: HTMLDivElement;
let root: Root;
const feed = { count: 1, page: 1, page_size: 20, catalog: [{ key: 'agent', label: '内置科研Agent', path: '/agent' }], results: [
  { id: 1, author_name: '成员甲', content: '<script>原始意见</script>', features: ['agent'], created_at: '2026-09-15T06:00:00Z' }
] };
const button = (text: string) => Array.from(host.querySelectorAll('button')).find((item) => item.textContent === text)!;
beforeEach(async () => {
  vi.clearAllMocks(); Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.mocked(apiFetch).mockImplementation(async () => new Response(JSON.stringify(feed)));
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<MemoryRouter><FeedbackView /></MemoryRouter>));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
it('shows identity, timestamp and feature links while rendering feedback as text', () => {
  expect(host.textContent).toContain('成员甲');
  expect(host.querySelector('time')?.dateTime).toBe('2026-09-15T06:00:00Z');
  expect(host.querySelector('script')).toBeNull();
  expect(host.querySelector('a')?.getAttribute('href')).toBe('/agent');
  expect(button('提交意见').disabled).toBe(true);
});
it('inserts a feature mention and retries a lost response without changing its request ID', async () => {
  await act(async () => button('@ 关联功能').click());
  await act(async () => button('@内置科研Agent').click());
  expect(host.querySelector('textarea')?.value).toBe('@内置科研Agent ');
  const fetch = vi.mocked(apiFetch);
  fetch.mockRejectedValueOnce(new Error('网络中断'));
  await act(async () => { button('提交意见').click(); button('提交意见').click(); });
  expect(host.textContent).toContain('网络中断');
  await act(async () => button('提交意见').click());
  const posts = fetch.mock.calls.filter((call) => call[1]?.method === 'POST');
  expect(posts).toHaveLength(2);
  expect(posts[0][1]?.body).toBe(posts[1][1]?.body);
  expect(host.querySelector('textarea')?.value).toBe('');
  expect(host.textContent).toContain('意见已记录');
});
