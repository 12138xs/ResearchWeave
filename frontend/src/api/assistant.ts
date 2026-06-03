import { apiFetch, readResponsePayload } from './client';

export function fetchAssistantSessions() {
  return apiFetch('/api/assistant/sessions/').then(readResponsePayload);
}

export function createAssistantSession(payload: object) {
  return apiFetch('/api/assistant/sessions/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(readResponsePayload);
}

export function sendAssistantMessage(sessionId: number, question: string) {
  return apiFetch(`/api/assistant/sessions/${sessionId}/messages/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  }).then(readResponsePayload);
}
