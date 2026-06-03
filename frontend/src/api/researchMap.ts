import { apiFetch, readResponsePayload } from './client';

export function fetchKnowledgeSpaceMap(spaceId: number) {
  return apiFetch(`/api/knowledge-spaces/${spaceId}/map/`).then(readResponsePayload);
}

export function enqueueKnowledgeSpaceMap(spaceId: number) {
  return apiFetch(`/api/knowledge-spaces/${spaceId}/map/generate/`, { method: 'POST' }).then(readResponsePayload);
}
