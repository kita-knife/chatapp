export interface ChatSession {
  id: string;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
}

export interface ModelInfo {
  provider: string;
  model: string;
}

export interface StreamChunk {
  delta?: string;
  finish_reason?: string;
  error?: string;
}

async function jsonRequest<T>(input: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(input, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => jsonRequest<{ status: string }>('/api/health'),
  listModels: () => jsonRequest<ModelInfo[]>('/api/chat/models'),
  listSessions: () => jsonRequest<ChatSession[]>('/api/chat/sessions'),
  createSession: (title?: string, model?: string) =>
    jsonRequest<ChatSession>('/api/chat/sessions', {
      method: 'POST',
      body: JSON.stringify({ title, model }),
    }),
  getSession: (id: string) => jsonRequest<ChatSession>(`/api/chat/sessions/${id}`),
  deleteSession: (id: string) =>
    jsonRequest<{ status: string }>(`/api/chat/sessions/${id}`, { method: 'DELETE' }),
  listMessages: (id: string) =>
    jsonRequest<ChatMessage[]>(`/api/chat/sessions/${id}/messages`),
  streamMessage: async function* (
    sessionId: string,
    content: string,
    model?: string,
  ): AsyncGenerator<StreamChunk> {
    const res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
      method: 'POST',
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
