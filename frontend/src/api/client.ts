export function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const method = (init.method ?? 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method) && !headers.has('X-CSRFToken')) {
    const csrfToken = csrfTokenFromCookie();
    if (csrfToken) headers.set('X-CSRFToken', csrfToken);
  }
  return fetch(input, { ...init, headers, credentials: init.credentials ?? 'same-origin' });
}

export function csrfTokenFromCookie() {
  if (typeof document === 'undefined') return '';
  return document.cookie
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith('csrftoken='))
    ?.slice('csrftoken='.length) ?? '';
}

export async function readResponsePayload(response: Response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

export function payloadMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== 'object') return fallback;
  const collectMessages = (value: unknown, prefix = ''): string[] => {
    if (typeof value === 'string' && value.trim()) return [`${prefix}${value}`];
    if (Array.isArray(value)) return value.flatMap((item) => collectMessages(item, prefix));
    if (value && typeof value === 'object') {
      return Object.entries(value).flatMap(([key, item]) => {
        const label = key === 'non_field_errors' || key === 'detail' ? '' : `${key}: `;
        return collectMessages(item, prefix || label);
      });
    }
    return [];
  };
  const detail = 'detail' in payload ? payload.detail : undefined;
  const file = 'file' in payload ? payload.file : undefined;
  if (Array.isArray(file) && typeof file[0] === 'string') return file[0];
  if (typeof detail === 'string' && detail.trim()) return detail;
  const messages = collectMessages(payload);
  if (messages.length > 0) return messages.slice(0, 4).join('; ');
  return fallback;
}
