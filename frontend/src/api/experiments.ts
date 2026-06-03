import { apiFetch, readResponsePayload } from './client';

export function fetchExperiments(path = '/api/experiments/') {
  return apiFetch(path).then(readResponsePayload);
}

export function fetchExperiment(id: number) {
  return apiFetch(`/api/experiments/${id}/`).then(readResponsePayload);
}

export function createExperiment(payload: object) {
  return apiFetch('/api/experiments/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(readResponsePayload);
}

export function createExperimentRun(projectId: number, payload: object) {
  return apiFetch(`/api/experiments/${projectId}/runs/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(readResponsePayload);
}

export function executeExperimentRun(runId: number) {
  return apiFetch(`/api/experiments/runs/${runId}/execute/`, { method: 'POST' }).then(readResponsePayload);
}
