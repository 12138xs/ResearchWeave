export type HealthState = {
  status: 'checking' | 'ok' | 'degraded';
  checks: Record<string, string | number | boolean>;
  release?: ReleaseInfo;
};

export type ReleaseInfo = {
  product: string;
  version: string;
  released_at: string;
  summary: string;
  migration_state: string;
};

export type ThemeMode = 'light' | 'dark';
