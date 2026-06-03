export type AuthUser = {
  id: number;
  username: string;
  email: string;
  is_staff: boolean;
  is_superuser: boolean;
};

export type AuthSession = {
  authenticated: boolean;
  user: AuthUser | null;
  csrf_token?: string;
};
