import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type User } from '@/api/client';

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
    onSuccess: () => {
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
