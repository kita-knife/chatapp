import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type ChatMessage, type ChatSession, type ModelInfo } from '../api/client';

export function useChat() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [model, setModel] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<string>('unknown');
  const abortRef = useRef<AbortController | null>(null);

  const refreshSessions = useCallback(async () => {
    try {
      const list = await api.listSessions();
      setSessions(list);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const h = await api.health();
      setHealth(h.status);
    } catch {
      setHealth('down');
    }
  }, []);

  const refreshModels = useCallback(async () => {
    try {
      const m = await api.listModels();
      setModels(m);
      if (m.length > 0 && !model) setModel(m[0]!.model);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [model]);

  useEffect(() => {
    refreshHealth();
    refreshModels();
    refreshSessions();
  }, [refreshHealth, refreshModels, refreshSessions]);

  const loadMessages = useCallback(async (sessionId: string) => {
    try {
      const list = await api.listMessages(sessionId);
      setMessages(list);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    if (currentSessionId) {
      loadMessages(currentSessionId);
    } else {
      setMessages([]);
    }
  }, [currentSessionId, loadMessages]);

  const newSession = useCallback(async () => {
    try {
      const created = await api.createSession(undefined, model || undefined);
      setCurrentSessionId(created.id);
      await refreshSessions();
    } catch (err) {
      setError((err as Error).message);
    }
  }, [model, refreshSessions]);

  const selectSession = useCallback((id: string) => {
    setCurrentSessionId(id);
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const send = useCallback(async () => {
    if (!input.trim() || streaming) return;
    setError(null);
    let sessionId = currentSessionId;
    if (!sessionId) {
      const created = await api.createSession(undefined, model || undefined);
      sessionId = created.id;
      setCurrentSessionId(created.id);
      await refreshSessions();
    }
    const userContent = input.trim();
    setInput('');
    const userMessage: ChatMessage = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content: userContent,
      created_at: new Date().toISOString(),
    };
    const assistantId = `temp-${Date.now() + 1}`;
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      for await (const chunk of api.streamMessage(sessionId, userContent, model || undefined)) {
        if (chunk.error) {
          setError(chunk.error);
        }
        if (chunk.delta) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + chunk.delta } : m,
            ),
          );
        }
        if (chunk.finish_reason) {
          // no-op; UI will rerender on next listMessages
        }
      }
      // refresh from server to get canonical IDs/timestamps
      await loadMessages(sessionId);
      await refreshSessions();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [currentSessionId, input, streaming, model, loadMessages, refreshSessions]);

  const removeSession = useCallback(
    async (id: string) => {
      try {
        await api.deleteSession(id);
        if (currentSessionId === id) setCurrentSessionId(null);
        await refreshSessions();
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [currentSessionId, refreshSessions],
  );

  return {
    sessions,
    models,
    currentSessionId,
    messages,
    input,
    setInput,
    model,
    setModel,
    streaming,
    error,
    health,
    send,
    stop,
    newSession,
    selectSession,
    removeSession,
  };
}
