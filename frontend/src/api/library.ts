import { apiFetch, readResponsePayload } from './client';

export function fetchCatalogStats() {
  return apiFetch('/api/catalog/stats/').then(readResponsePayload);
}

export function fetchKnowledgeSpaces(query = '') {
  return apiFetch(`/api/knowledge-spaces/${query}`).then(readResponsePayload);
}

export function createKnowledgeSpace(payload: object) {
  return apiFetch('/api/knowledge-spaces/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(readResponsePayload);
}

export function archiveKnowledgeSpace(id: number) {
  return apiFetch(`/api/knowledge-spaces/${id}/archive/`, { method: 'POST' }).then(
    readResponsePayload,
  );
}
