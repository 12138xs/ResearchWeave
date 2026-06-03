import { useEffect, useState } from 'react';

import { apiFetch } from '../api/client';
import type { AuthSession } from '../features/auth/types';
import type { HealthState } from '../shared/types';

export function useHealth(): HealthState {
  const [health, setHealth] = useState<HealthState>({ status: 'checking', checks: {} });

  useEffect(() => {
    let mounted = true;
    apiFetch('/api/health/')
      .then((response) => response.json())
      .then((data) => {
        if (!mounted) return;
        setHealth({
          status: data.status === 'ok' ? 'ok' : 'degraded',
          checks: data.checks ?? {},
          release: data.release
        });
      })
      .catch(() => {
        if (!mounted) return;
        setHealth({ status: 'degraded', checks: {} });
      });
    return () => {
      mounted = false;
    };
  }, []);

  return health;
}

export function useAuthSession() {
  const [session, setSession] = useState<AuthSession>({ authenticated: false, user: null });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    apiFetch('/api/me/')
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((payload: AuthSession) => {
        if (!mounted) return;
        setSession(payload);
      })
      .catch(() => {
        if (!mounted) return;
        setSession({ authenticated: false, user: null });
      })
      .finally(() => {
        if (!mounted) return;
        setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  return { session, setSession, loading };
}

export function useApiData<T>(url: string, fallback: T): { data: T; loading: boolean; error: boolean } {
  const [data, setData] = useState<T>(fallback);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let mounted = true;
    if (!url) {
      setData(fallback);
      setLoading(false);
      setError(false);
      return () => {
        mounted = false;
      };
    }
    setLoading(true);
    apiFetch(url)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((payload) => {
        if (!mounted) return;
        setData(payload);
        setError(false);
      })
      .catch(() => {
        if (!mounted) return;
        setData(fallback);
        setError(true);
      })
      .finally(() => {
        if (!mounted) return;
        setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [url]);

  return { data, loading, error };
}
