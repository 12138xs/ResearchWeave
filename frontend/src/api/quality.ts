import { apiFetch, readResponsePayload } from './client';

export function fetchQualityIssues(path = '/api/quality/issues/?status=open') {
  return apiFetch(path).then(readResponsePayload);
}

export function patchQualityIssue(id: number, payload: object) {
  return apiFetch(`/api/quality/issues/${id}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(readResponsePayload);
}

export function enqueueQualityAudit() {
  return apiFetch('/api/quality/audits/enqueue/', { method: 'POST' }).then(readResponsePayload);
}
