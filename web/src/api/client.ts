import { notifyAuthError } from '@/authEvents';

export interface UserPreferences {
  default_mode: 'simple' | 'knowledge' | 'think';
  default_model: string | null;
  system_prompt_overrides: {
    think: string | null;
    knowledge: string | null;
  };
  ui_language: 'zh' | 'en';
}

export interface User {
  id: string;
  username: string;
  role: 'root' | 'admin' | 'user';
  created_at?: string;
  last_login_at?: string | null;
  preferences?: UserPreferences;
}

export interface AuthStatus {
  authenticated: boolean;
  user: User | null;
}

export interface ChatSession {
  id: string;
  title: string;
  model: string;
  owner_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatTurn {
  id: string;
  session_id: string;
  user_content: string;
  assistant_content: string | null;
  user_tokens_in: number;
  assistant_tokens_out: number;
  status: 'pending' | 'streaming' | 'complete' | 'error' | 'interrupted';
  created_at: string;
  updated_at: string;
}

export interface ModelInfo {
  provider: string;
  model: string;
}

export interface StreamChunk {
  delta?: string;
  finish_reason?: string | null;
  error?: string | null;
  tokens_in?: number;
  tokens_out?: number;
}

export interface ConnectivityResult {
  ok: boolean;
  provider: string;
  model: string;
  latency_ms: number;
  error: string | null;
}

const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, '') || '/api';

function apiPath(path: string): string {
  // Allow callers to keep using `/api/...` style paths; strip the leading
  // `/api` so we don't double-prefix when API_BASE is `/api` (the default).
  let p = path.startsWith('/') ? path : '/' + path;
  if (p === '/api' || p.startsWith('/api/')) {
    p = p === '/api' ? '/' : p.slice(4);
  }
  return `${API_BASE}${p}`;
}

async function jsonRequest<T>(input: string, init: RequestInit = {}): Promise<T> {
  const path = apiPath(input);
  const res = await fetch(path, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    const err = new ApiError(
      `${res.status} ${res.statusText}: ${detail}`,
      res.status,
      path,
    );
    // Surface 401s to the global auth guard even when the caller didn't
    // go through TanStack Query (e.g. plain fetch from a useCallback).
    notifyAuthError(err);
    throw err;
  }
  return res.json() as Promise<T>;
}

/**
 * Tagged error thrown by every API call on a non-2xx response. Carries
 * the HTTP status and the request path so the global auth guard in
 * `authGuard.ts` can decide whether to log the user out and redirect.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly path: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export const api = {
  // ----- auth -----
  authStatus: () => jsonRequest<AuthStatus>('/api/auth/status'),
  login: (username: string, password: string) =>
    jsonRequest<AuthStatus>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: () => jsonRequest<{ status: string }>('/api/auth/logout', { method: 'POST' }),
  me: () => jsonRequest<User>('/api/auth/me'),

  // ----- user management (root only) -----
  listUsers: () => jsonRequest<User[]>('/api/auth/users'),
  createUser: (username: string, password: string, role: 'admin' | 'user') =>
    jsonRequest<User>('/api/auth/users', {
      method: 'POST',
      body: JSON.stringify({ username, password, role }),
    }),
  deleteUser: (id: string) =>
    jsonRequest<{ status: string }>(`/api/auth/users/${id}`, { method: 'DELETE' }),
  changePassword: (id: string, new_password: string) =>
    jsonRequest<{ status: string }>(`/api/auth/users/${id}/password`, {
      method: 'PATCH',
      body: JSON.stringify({ new_password }),
    }),

  // ----- preferences -----
  getMyPreferences: () => jsonRequest<UserPreferences>('/api/auth/me/preferences'),
  updateMyPreferences: (preferences: Partial<UserPreferences>, replaceAll = false) =>
    jsonRequest<UserPreferences>('/api/auth/me/preferences', {
      method: 'PATCH',
      body: JSON.stringify({ preferences, replace_all: replaceAll }),
    }),
  getUserPreferences: (id: string) =>
    jsonRequest<UserPreferences>(`/api/auth/users/${id}/preferences`),
  updateUserPreferences: (
    id: string,
    preferences: Partial<UserPreferences>,
    replaceAll = false,
  ) =>
    jsonRequest<UserPreferences>(`/api/auth/users/${id}/preferences`, {
      method: 'PATCH',
      body: JSON.stringify({ preferences, replace_all: replaceAll }),
    }),

  // ----- chat -----
  health: () => jsonRequest<{ status: string }>('/api/health'),
  listModels: () => jsonRequest<ModelInfo[]>('/api/chat/models'),
  connectivity: (model?: string) => {
    const qs = model ? `?model=${encodeURIComponent(model)}` : '';
    return jsonRequest<ConnectivityResult>(`/api/chat/connectivity${qs}`);
  },
  listSessions: () => jsonRequest<ChatSession[]>('/api/chat/sessions'),
  createSession: (title?: string, model?: string) =>
    jsonRequest<ChatSession>('/api/chat/sessions', {
      method: 'POST',
      body: JSON.stringify({ title, model }),
    }),
  getSession: (id: string) => jsonRequest<ChatSession>(`/api/chat/sessions/${id}`),
  deleteSession: (id: string) =>
    jsonRequest<{ status: string }>(`/api/chat/sessions/${id}`, { method: 'DELETE' }),
  listMessages: (id: string) => jsonRequest<ChatTurn[]>(`/api/chat/sessions/${id}/messages`),
  streamMessage: async function* (
    sessionId: string,
    content: string,
    model?: string,
    mode?: string,
  ): AsyncGenerator<StreamChunk> {
    const path = apiPath(`/api/chat/sessions/${sessionId}/messages`);
    const res = await fetch(path, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, model, mode }),
    });
    if (!res.ok || !res.body) {
      const err = new ApiError(
        `Stream failed: ${res.status} ${res.statusText}`,
        res.status,
        path,
      );
      notifyAuthError(err);
      throw err;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const event = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        for (const line of event.split('\n')) {
          if (line.startsWith('data: ')) {
            const payload = line.slice(6);
            try {
              yield JSON.parse(payload) as StreamChunk;
            } catch {
              // ignore malformed chunk
            }
          }
        }
      }
    }
  },
};
