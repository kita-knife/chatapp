import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type User, type UserPreferences } from '@/api/client';

export type AuthState = {
  user: User | null;
  isReady: boolean;
  isAuthenticated: boolean;
  isRoot: boolean;
};

export function useAuth(): AuthState {
  const status = useQuery({
    queryKey: ['auth', 'status'],
    queryFn: () => api.authStatus(),
    staleTime: 30_000,
    retry: false,
  });
  return {
    user: status.data?.user ?? null,
    isReady: status.isFetched,
    isAuthenticated: !!status.data?.authenticated,
    isRoot: status.data?.user?.role === 'root',
  };
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      api.login(username, password),
    onSuccess: (data) => {
      // Login response is the same shape as `authStatus`; writing it
      // directly into the cache makes `useAuth()` see the authenticated
      // user synchronously on the next render. Without this, the first
      // click navigates to /chat but ProtectedRoute still reads the
      // pre-login cache (user=null) and bounces back to /login, forcing
      // a second click and creating a duplicate auth_session row.
      //
      // Note: the login response doesn't include `preferences` (only
      // authStatus does). Components that need preferences fetch them
      // via `useMyPreferences()` separately; we don't backfill here.
      qc.setQueryData(['auth', 'status'], data);
      // Trigger a background refetch so the full user (with preferences)
      // gets reconciled lazily once any observer (e.g. ProtectedRoute)
      // mounts and observes the query.
      qc.invalidateQueries({ queryKey: ['auth'] });
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.logout(),
    onSuccess: () => {
      qc.clear();
    },
  });
}

export function useMyPreferences() {
  return useQuery({
    queryKey: ['auth', 'me', 'preferences'],
    queryFn: () => api.getMyPreferences(),
    staleTime: 60_000,
  });
}

export function useUpdateMyPreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      preferences,
      replaceAll = false,
    }: {
      preferences: Partial<UserPreferences>;
      replaceAll?: boolean;
    }) => api.updateMyPreferences(preferences, replaceAll),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['auth', 'me', 'preferences'] });
      qc.invalidateQueries({ queryKey: ['auth'] });
    },
  });
}

export function useUserPreferences(userId: string | null) {
  return useQuery({
    queryKey: ['admin', 'users', userId, 'preferences'],
    queryFn: () => api.getUserPreferences(userId!),
    enabled: !!userId,
  });
}

export function useUpdateUserPreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      userId,
      preferences,
      replaceAll = false,
    }: {
      userId: string;
      preferences: Partial<UserPreferences>;
      replaceAll?: boolean;
    }) => api.updateUserPreferences(userId, preferences, replaceAll),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['admin', 'users', vars.userId, 'preferences'] });
    },
  });
}