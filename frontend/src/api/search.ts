import { apiFetch, payloadMessage, readResponsePayload } from './client';

export function fetchSearch(path: string) {
  return apiFetch(path).then(readResponsePayload);
}

export function evidenceSearchUrl(query: string) {
  return query.trim() ? `/api/search/evidence/?${new URLSearchParams({ q: query, limit: '10' })}` : '';
}

export async function assistEvidenceSearch(query: string) {
  const response = await apiFetch('/api/search/evidence/assist/', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ q: query, limit: 10 })
  });
  const payload = await readResponsePayload(response);
  if (!response.ok) throw new Error(payloadMessage(payload, '增强检索暂不可用。'));
  return payload;
}

export function enqueueSearchReindex() {
  return apiFetch('/api/search/reindex/', { method: 'POST' }).then(readResponsePayload);
}
