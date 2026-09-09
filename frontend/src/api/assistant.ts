import { apiFetch, payloadMessage, readResponsePayload } from './client';
import type { AssistantExchange, AssistantSession } from '../features/assistant/types';

async function request<T>(url: string, payload?: object): Promise<T> {
  const response = await apiFetch(url, payload ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  } : {});
  const data = await readResponsePayload(response);
  if (!response.ok) throw new Error(payloadMessage(data, '请求失败，请重试。'));
  return data as T;
}
export function fetchAssistantSessions() {
  return request<AssistantSession[]>('/api/assistant/sessions/');
}
export function fetchAssistantSession(id: number) {
  return request<AssistantSession>(`/api/assistant/sessions/${id}/`);
}
export function createAssistantSession(payload: object) {
  return request<AssistantSession>('/api/assistant/sessions/', payload);
}
export function sendAssistantMessage(sessionId: number, question: string, requestId: string) {
  return request<AssistantExchange>(`/api/assistant/sessions/${sessionId}/messages/`, { question, request_id: requestId });
}
export function controlAssistantExchange(exchange: AssistantExchange, action: 'cancel' | 'retry') {
  return request<AssistantExchange>(`/api/assistant/sessions/${exchange.session}/exchanges/${exchange.id}/`, { action, attempt: exchange.attempt });
}
