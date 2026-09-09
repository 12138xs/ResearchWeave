import { apiFetch, readResponsePayload } from './client';

export function fetchSearch(path: string) {
  return apiFetch(path).then(readResponsePayload);
}

export function evidenceSearchUrl(query: string) {
  return query.trim() ? `/api/search/evidence/?${new URLSearchParams({ q: query, limit: '10' })}` : '';
}

export function enqueueSearchReindex() {
  return apiFetch('/api/search/reindex/', { method: 'POST' }).then(readResponsePayload);
}
