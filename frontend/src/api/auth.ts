import { apiFetch, readResponsePayload } from './client';

export function fetchSession() {
  return apiFetch('/api/me/').then(readResponsePayload);
}

export function login(username: string, password: string) {
  return apiFetch('/api/auth/login/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  }).then(readResponsePayload);
}

export function logout() {
  return apiFetch('/api/auth/logout/', { method: 'POST' }).then(readResponsePayload);
}
