import { beforeEach, describe, expect, it, vi } from 'vitest';

import { apiFetch, csrfTokenFromCookie, payloadMessage } from './client';

describe('api client', () => {
  beforeEach(() => {
    document.cookie = 'csrftoken=; Max-Age=0; path=/';
    vi.restoreAllMocks();
  });

  it('reads the Django csrf token from cookies', () => {
    document.cookie = 'csrftoken=test-token; path=/';

    expect(csrfTokenFromCookie()).toBe('test-token');
  });

  it('adds the csrf header to unsafe same-origin requests', async () => {
    document.cookie = 'csrftoken=test-token; path=/';
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'));

    await apiFetch('/api/papers/upload/', { method: 'POST' });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe('same-origin');
    expect(new Headers(init.headers).get('X-CSRFToken')).toBe('test-token');
  });

  it('does not add csrf headers to safe requests', async () => {
    document.cookie = 'csrftoken=test-token; path=/';
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'));

    await apiFetch('/api/me/');

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).has('X-CSRFToken')).toBe(false);
  });

  it('formats nested API errors into a concise message', () => {
    const message = payloadMessage({ title: ['不能为空'], detail: 'ignored' }, 'fallback');

    expect(message).toBe('ignored');
  });
});
