import { apiFetch, readResponsePayload } from './client';

export function fetchDocuments(path = '/api/documents/') {
  return apiFetch(path).then(readResponsePayload);
}

export function saveDocument(path: string, payload: object, method: 'POST' | 'PATCH') {
  return apiFetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(readResponsePayload);
}
