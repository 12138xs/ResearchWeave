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
const writeQuestion = async (text: string) => act(async () => {
  const field = host.querySelector('textarea')!;
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, text);
  field.dispatchEvent(new Event('input', { bubbles: true }));
});
const choosePreset = async (value: string) => act(async () => {
  const field = host.querySelector<HTMLSelectElement>('select[aria-label="提示词模板"]')!;
  field.value = value; field.dispatchEvent(new Event('change', { bubbles: true }));
});
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
  await writeQuestion('复杂几何有哪些相关工作？');
  expect(button('提问').disabled).toBe(false);
  expect(host.querySelector('details')?.open).toBe(false);
  await act(async () => button('提问').click());
  expect(host.textContent).toContain('响应丢失');
  await act(async () => button('提问').click());
  expect(start).toHaveBeenCalledTimes(2);
  expect(start.mock.calls[0][2]).toEqual({ content_types: ['paper', 'document', 'experiment', 'other'] });
  expect(start.mock.calls[0][1]).toBe(start.mock.calls[1][1]);
  expect(button('继续提问')).toBeDefined();
});

it('blocks rapid double submission and follows up in the existing session', async () => {
  vi.mocked(startAssistantConversation).mockResolvedValue(session);
  await writeQuestion('复杂几何有哪些相关工作？');
  await act(async () => { const ask = button('提问'); ask.click(); ask.click(); });
  expect(startAssistantConversation).toHaveBeenCalledTimes(1);
  vi.mocked(sendAssistantMessage).mockResolvedValue({ id: 1, session: 42, question: '追问', answer: '', sources: [], status: 'completed', attempt: 1, progress: '', error: '', updated_at: '', model: '', usage: {}, context_warning: '', created_at: '' });
  await writeQuestion('如何改进？');
  await act(async () => button('继续提问').click());
  expect(sendAssistantMessage).toHaveBeenCalledTimes(1);
  expect(vi.mocked(sendAssistantMessage).mock.calls[0][0]).toBe(42);
  expect(startAssistantConversation).toHaveBeenCalledTimes(1);
});

it('selects at most one optional preset without replacing the question', async () => {
  const start = vi.mocked(startAssistantConversation).mockResolvedValue(session);
  const field = host.querySelector<HTMLSelectElement>('select[aria-label="提示词模板"]')!;
  expect(field.value).toBe('');
  expect(field.multiple).toBe(false);
  await writeQuestion('我的研究问题');
  await choosePreset('0'); await choosePreset('2');
  expect(host.querySelector('textarea')!.value).toBe('我的研究问题');
  await act(async () => button('提问').click());
  expect(start.mock.calls[0][0]).toContain('分析所述工作的不足');
  expect(start.mock.calls[0][0]).not.toContain('总结所问方向');
  expect(field.value).toBe('');
});

it('clearing a preset submits only the question', async () => {
  const start = vi.mocked(startAssistantConversation).mockResolvedValue(session);
  await writeQuestion('我的研究问题');
  await choosePreset('1'); await choosePreset('');
  await act(async () => button('提问').click());
  expect(start.mock.calls[0][0]).toBe('我的研究问题');
});

it('requires a category and sends only the selected categories', async () => {
  const start = vi.mocked(startAssistantConversation).mockResolvedValue(session);
  expect(host.querySelector('[aria-label="来源编号"]')).toBeNull();
  const fields = Array.from(host.querySelectorAll<HTMLInputElement>('fieldset input[type="checkbox"]'));
  expect(fields).toHaveLength(5);
  expect(fields[4].disabled).toBe(true);
  await writeQuestion('有哪些相关论文？');
  await act(async () => fields.slice(0, 4).forEach((field) => field.click()));
  expect(button('提问').disabled).toBe(true);
  await act(async () => fields[0].click());
  await act(async () => button('提问').click());
  expect(start.mock.calls[0][2]).toEqual({ content_types: ['paper'] });
});
