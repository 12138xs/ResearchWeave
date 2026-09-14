import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AssistantView } from './AssistantView';
import { startAssistantConversation, sendAssistantMessage } from '../../api/assistant';

vi.mock('../../app/hooks', () => ({ useApiData: () => ({ data: [] }) }));
vi.mock('./PersonalWorkspace', () => ({ PersonalWorkspace: () => null }));
vi.mock('../../api/assistant', () => ({ startAssistantConversation: vi.fn(), sendAssistantMessage: vi.fn(), fetchAssistantSession: vi.fn(), controlAssistantExchange: vi.fn() }));
let host: HTMLDivElement;
let root: Root;
const session = { id: 42, title: '研究', mode: 'freeform_scoped' as const, scope_json: {}, created_by: 1, created_at: '', updated_at: '', exchanges: [] };
const button = (text: string) => Array.from(host.querySelectorAll('button')).find((item) => item.textContent === text)!;
beforeEach(async () => {
  vi.clearAllMocks();
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<AssistantView />));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

it('starts from a question without selecting a session or materials, and reuses a lost-response request', async () => {
  const start = vi.mocked(startAssistantConversation);
  start.mockRejectedValueOnce(new Error('响应丢失')).mockResolvedValueOnce(session);
  await act(async () => button('研究进展').click());
  expect(button('提问').disabled).toBe(false);
  expect(host.querySelector('details')?.open).toBe(false);
  await act(async () => button('提问').click());
  expect(host.textContent).toContain('响应丢失');
  await act(async () => button('提问').click());
  expect(start).toHaveBeenCalledTimes(2);
  expect(start.mock.calls[0][2]).toEqual({});
  expect(start.mock.calls[0][1]).toBe(start.mock.calls[1][1]);
  expect(button('继续提问')).toBeDefined();
});

it('blocks rapid double submission and follows up in the existing session', async () => {
  vi.mocked(startAssistantConversation).mockResolvedValue(session);
  await act(async () => button('研究进展').click());
  await act(async () => { const ask = button('提问'); ask.click(); ask.click(); });
  expect(startAssistantConversation).toHaveBeenCalledTimes(1);
  vi.mocked(sendAssistantMessage).mockResolvedValue({ id: 1, session: 42, question: '追问', answer: '', sources: [], status: 'completed', attempt: 1, progress: '', error: '', updated_at: '', model: '', usage: {}, context_warning: '', created_at: '' });
  await act(async () => button('工作改进').click());
  await act(async () => button('继续提问').click());
  expect(sendAssistantMessage).toHaveBeenCalledTimes(1);
  expect(vi.mocked(sendAssistantMessage).mock.calls[0][0]).toBe(42);
  expect(startAssistantConversation).toHaveBeenCalledTimes(1);
});
