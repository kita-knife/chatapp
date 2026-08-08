export interface User {
  id: string;
  username: string;
  role: 'root' | 'admin' | 'user';
  created_at?: string;
  last_login_at?: string | null;
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

async function jsonRequest<T>(input: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(input, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  return res.json() as Promise<T>;
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
  ): AsyncGenerator<StreamChunk> {
    const res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, model }),
    });
    if (!res.ok || !res.body) {
      throw new Error(`Stream failed: ${res.status} ${res.statusText}`);
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
