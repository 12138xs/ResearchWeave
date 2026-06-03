import { apiFetch, readResponsePayload } from './client';

export function fetchTasks(query: string) {
  return apiFetch(`/api/tasks/?${query}`).then(readResponsePayload);
}

export function fetchTaskStatus(ids: string) {
  return apiFetch(`/api/tasks/status/?ids=${encodeURIComponent(ids)}`).then(readResponsePayload);
}
