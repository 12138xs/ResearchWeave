import { apiFetch, readResponsePayload } from './client';

export function fetchSearch(path: string) {
  return apiFetch(path).then(readResponsePayload);
}

export function enqueueSearchReindex() {
  return apiFetch('/api/search/reindex/', { method: 'POST' }).then(readResponsePayload);
}
