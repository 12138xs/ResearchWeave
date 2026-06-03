import { apiFetch, readResponsePayload } from './client';

export function fetchPapers(path = '/api/papers/') {
  return apiFetch(path).then(readResponsePayload);
}

export function patchPaperMetadata(id: number, payload: object) {
  return apiFetch(`/api/papers/${id}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(readResponsePayload);
}

export function triggerLightProcess(id: number, payload: object = {}) {
  return apiFetch(`/api/papers/${id}/light-process/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(readResponsePayload);
}

export function triggerDeepProcess(id: number, payload: object = {}) {
  return apiFetch(`/api/papers/${id}/trigger-deep-process/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(readResponsePayload);
}

export function fetchPaperReadingState(id: number) {
  return apiFetch(`/api/papers/${id}/reading-state/`).then(readResponsePayload);
}

export function patchPaperReadingState(id: number, payload: object) {
  return apiFetch(`/api/papers/${id}/reading-state/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(readResponsePayload);
}

export function fetchPaperReadingReviews(id: number) {
  return apiFetch(`/api/papers/${id}/reading-reviews/`).then(readResponsePayload);
}

export function createPaperReadingReview(id: number, payload: object) {
  return apiFetch(`/api/papers/${id}/reading-reviews/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(readResponsePayload);
}

export function patchPaperReadingReview(paperId: number, reviewId: number, payload: object) {
  return apiFetch(`/api/papers/${paperId}/reading-reviews/${reviewId}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(readResponsePayload);
}
