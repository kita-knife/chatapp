import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  api,
  type ChatSession,
  type ChatTurn,
  type ConnectivityResult,
  type ModelInfo,
} from '@/api/client';
import { useAuth } from '@/features/auth/useAuth';
import { useLogout } from '@/features/auth/useAuth';
import type { AgentMode } from '@/components/ChatInput';

/**
 * Chat state hook. The URL (`/chat/:sessionId`) is the single source of truth
 * for which session is active — `currentSessionId` is derived from
 * `useParams()`. All actions either create a new session (and navigate) or
 * navigate to an existing one.
 */
export function useChat() {
  const navigate = useNavigate();
  const auth = useAuth();
  const logout = useLogout();

  const { sessionId: routeSessionId } = useParams<{ sessionId?: string }>();
  const currentSessionId: string | null = routeSessionId ?? null;
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState('');
  const [model, setModel] = useState('');
  const [mode, setModeState] = useState<AgentMode>(() => {
    // Prefer the user's stored preference; fall back to localStorage; default simple.
    const fromLs = typeof window !== 'undefined' ? window.localStorage.getItem('chatapp.mode') : null;
    if (fromLs === 'simple' || fromLs === 'knowledge' || fromLs === 'think') return fromLs;
    return 'simple';
  });
  const setMode = useCallback((m: AgentMode) => {
    setModeState(m);
    try {
      window.localStorage.setItem('chatapp.mode', m);
    } catch {
      /* ignore */
    }
  }, []);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<string>('unknown');
  const [connectivity, setConnectivity] = useState<ConnectivityResult | null>(null);
  const [checkingConn, setCheckingConn] = useState(false);

  // Reset transient state on logout.
  useEffect(() => {
    if (auth.isReady && !auth.user) {
      setSessions([]);
      setTurns([]);
      setInput('');
      setModel('');
      setError(null);
      try {
        window.localStorage.removeItem('chatapp.mode');
        window.localStorage.removeItem('chatapp.model');
      } catch {
        /* ignore */
      }
    }
  }, [auth.isReady, auth.user]);

  // Sync preferences from server into local state on login. Server is the
  // source of truth; the user picks a mode via the UI, which we also cache
  // locally for instant restore across reloads.
  useEffect(() => {
    const prefs = auth.user?.preferences;
    if (!prefs) return;
    if (
      (prefs.default_mode === 'simple' ||
        prefs.default_mode === 'knowledge' ||
        prefs.default_mode === 'think') &&
      prefs.default_mode !== mode
    ) {
      setMode(prefs.default_mode);
      try {
        window.localStorage.setItem('chatapp.mode', prefs.default_mode);
      } catch {
        /* ignore */
      }
    }
    if (prefs.default_model && !model) {
      setModel(prefs.default_model);
      try {
        window.localStorage.setItem('chatapp.model', prefs.default_model);
      } catch {
        /* ignore */
      }
    }
  }, [auth.isReady, auth.user]);

  const refreshSessions = useCallback(async () => {
    if (!auth.user) return;
    try {
      const list = await api.listSessions();
      setSessions(list);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [auth.user]);

  const refreshHealth = useCallback(async () => {
    try {
      const h = await api.health();
      setHealth(h.status);
    } catch {
      setHealth('down');
    }
  }, []);

  const refreshModels = useCallback(async () => {
    if (!auth.user) return;
    try {
      const m = await api.listModels();
      setModels(m);
      setModel((prev) => (prev ? prev : m[0]?.model ?? ''));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [auth.user]);

  const probeConnectivity = useCallback(
    async (targetModel?: string) => {
      if (!auth.user) return null;
      setCheckingConn(true);
      try {
        const res = await api.connectivity(targetModel ?? (model || undefined));
        setConnectivity(res);
        if (!res.ok) {
          setError(`${res.provider} failed: ${res.error}`);
        }
        return res;
      } catch (err) {
        const msg = (err as Error).message;
        setConnectivity({
          ok: false,
          provider: 'unknown',
          model: targetModel ?? model ?? '',
          latency_ms: 0,
          error: msg,
        });
        setError(msg);
        return null;
      } finally {
        setCheckingConn(false);
      }
    },
    [auth.user, model],
  );

  useEffect(() => {
    if (!auth.user) return;
    refreshHealth();
    refreshModels();
    refreshSessions();
    probeConnectivity();
  }, [auth.user, refreshHealth, refreshModels, refreshSessions, probeConnectivity]);

  // Tracks whether a stream is currently mutating `turns[]`. The URL-change
  // effect below must NOT clobber that local state — otherwise on /chat
  // (no session) the send()'s temp turn is replaced by the server's
  // response (real uuid) and subsequent chunk updates can't find the
  // temp id, freezing the UI at "streaming…".
  const streamingRef = useRef(false);

  // Load turns whenever the URL session id changes — but only when we're
  // not in the middle of streaming a message.
  useEffect(() => {
    if (!auth.user || !currentSessionId) {
      setTurns([]);
      return;
    }
    if (streamingRef.current) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await api.listMessages(currentSessionId);
        if (!cancelled) setTurns(list);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [auth.user, currentSessionId]);

  const newSession = useCallback(async () => {
    try {
      const created = await api.createSession(undefined, model || undefined);
      await refreshSessions();
      navigate(`/chat/${created.id}`);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [model, refreshSessions, navigate]);

  const selectSession = useCallback(
    (id: string) => {
      if (id === currentSessionId) return;
      navigate(`/chat/${id}`);
    },
    [currentSessionId, navigate],
  );

  const send = useCallback(async () => {
    if (!input.trim() || streaming) return;
    setError(null);

    const probe = await probeConnectivity(model || undefined);
    if (!probe || !probe.ok) return;

    let sessionId = currentSessionId;
    if (!sessionId) {
      try {
        const created = await api.createSession(undefined, model || undefined);
        sessionId = created.id;
        await refreshSessions();
        navigate(`/chat/${created.id}`);
      } catch (err) {
        setError((err as Error).message);
        return;
      }
    }

    const userContent = input.trim();
    const tempTurnId = `tmp-${Date.now()}`;
    const newTurn: ChatTurn = {
      id: tempTurnId,
      session_id: sessionId,
      user_content: userContent,
      assistant_content: '',
      user_tokens_in: 0,
      assistant_tokens_out: 0,
      status: 'streaming',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    setTurns((prev) => [...prev, newTurn]);
    setInput('');
    setStreaming(true);
    streamingRef.current = true;

    try {
      let lastTokensIn = 0;
      let lastTokensOut = 0;
      for await (const chunk of api.streamMessage(sessionId, userContent, model || undefined, mode)) {
        if (chunk.error) setError(chunk.error);
        if (chunk.delta) {
          setTurns((prev) =>
            prev.map((t) =>
              t.id === tempTurnId
                ? { ...t, assistant_content: (t.assistant_content || '') + chunk.delta }
                : t,
            ),
          );
        }
        if (typeof chunk.tokens_in === 'number') lastTokensIn = chunk.tokens_in;
        if (typeof chunk.tokens_out === 'number') lastTokensOut = chunk.tokens_out;
      }
      setTurns((prev) =>
        prev.map((t) =>
          t.id === tempTurnId
            ? {
                ...t,
                status: 'complete',
                user_tokens_in: lastTokensIn,
                assistant_tokens_out: lastTokensOut,
              }
            : t,
        ),
      );
      const list = await api.listSessions();
      setSessions(list);
    } catch (err) {
      setError((err as Error).message);
      setTurns((prev) =>
        prev.map((t) => (t.id === tempTurnId ? { ...t, status: 'error' } : t)),
      );
    } finally {
      streamingRef.current = false;
      setStreaming(false);
    }
  }, [currentSessionId, input, streaming, model, mode, probeConnectivity, refreshSessions, navigate]);

  const stop = useCallback(() => {
    // Streaming cannot be aborted yet without an AbortController on the
    // underlying fetch. The stream will run to completion. Future work.
  }, []);

  const removeSession = useCallback(
    async (id: string) => {
      try {
        await api.deleteSession(id);
        await refreshSessions();
        if (id === currentSessionId) {
          navigate('/chat');
        }
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [currentSessionId, refreshSessions, navigate],
  );

  const handleLogout = useCallback(() => {
    logout.mutate(undefined, {
      onSuccess: () => navigate('/login', { replace: true }),
    });
  }, [logout, navigate]);

  return {
    sessions,
    models,
    currentSessionId,
    turns,
    input,
    setInput,
    model,
    setModel,
    mode,
    setMode,
    streaming,
    error,
    health,
    connectivity,
    checkingConn,
    probeConnectivity,
    send,
    stop,
    newSession,
    selectSession,
    removeSession,
    user: auth.user,
    isRoot: auth.isRoot,
    handleLogout,
  };
}
