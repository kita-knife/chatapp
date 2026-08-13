/**
 * Chat state hook. The URL (`/chat/:sessionId`) is the single source of truth
 * for which session is active — `currentSessionId` is derived from
 * `useParams()`. All actions either create a new session (and navigate) or
 * navigate to an existing one.
 *
 * Shared state (read by both AppShell and ChatPage) lives in TanStack
 * Query's singleton cache so the two useChat instances see the same data.
 * Per-page state (input, turns, currentSessionId) stays local.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
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

export function useChat() {
  const navigate = useNavigate();
  const auth = useAuth();
  const logout = useLogout();
  const qc = useQueryClient();

  const { sessionId: routeSessionId } = useParams<{ sessionId?: string }>();
  const currentSessionId: string | null = routeSessionId ?? null;

  // —— Shared reads via TanStack Query (singleton cache) —————————————————

  // Sessions list — AppShell's sidebar reads this, ChatPage mutates it.
  const sessionsQuery = useQuery({
    queryKey: ['chat', 'sessions'],
    queryFn: () => api.listSessions(),
    enabled: !!auth.user,
    staleTime: 0,
  });
  const sessions = sessionsQuery.data ?? [];

  // API health — AppShell's pill.
  const healthQuery = useQuery<{ status: string }>({
    queryKey: ['api', 'health'],
    queryFn: () => api.health(),
    enabled: !!auth.user,
    staleTime: 30_000,
  });
  const health = healthQuery.data?.status ?? (healthQuery.isError ? 'down' : 'unknown');

  // Models list — AppShell's picker, ChatInput's picker, Settings' picker.
  const modelsQuery = useQuery<ModelInfo[]>({
    queryKey: ['chat', 'models'],
    queryFn: () => api.listModels(),
    enabled: !!auth.user,
    staleTime: 5 * 60_000,
  });
  const models = modelsQuery.data ?? [];

  // Connectivity probe — per-model. `defaultModel` (server-backed) is
  // the sidebar's selected default; `model` (declared below) is the
  // current chat selection. The probe is keyed on the default — when the
  // user changes the sidebar, the connectivity check refetches against
  // the new default.
  const defaultModel = auth.user?.preferences?.default_model ?? '';
  const mode: AgentMode =
    (auth.user?.preferences?.default_mode as AgentMode | undefined) ?? 'simple';
  const connectivityQuery = useQuery<ConnectivityResult | null>({
    queryKey: ['chat', 'connectivity', defaultModel || ''],
    queryFn: () => api.connectivity(defaultModel || undefined),
    enabled: !!auth.user,
    staleTime: 30_000,
    retry: false,
  });
  const connectivity = connectivityQuery.data ?? null;
  const refetchConnectivity = connectivityQuery.refetch;
  const checkingConn = connectivityQuery.isFetching;

  // `error` and `streaming` are UI state that needs to be visible across
  // every useChat instance (e.g. AppShell's error banner needs to see
  // errors raised inside ChatPage's send()). Storing them in the
  // TanStack Query singleton cache gives us that for free.
  const errorQuery = useQuery<{ msg: string | null; ts: number }>({
    queryKey: ['ui', 'error'],
    queryFn: () => ({ msg: null, ts: 0 }),
    initialData: { msg: null, ts: 0 },
    staleTime: Infinity,
  });
  const error = errorQuery.data?.msg ?? null;
  const setError = useCallback(
    (msg: string | null) => {
      qc.setQueryData(['ui', 'error'], { msg, ts: Date.now() });
    },
    [qc],
  );
  const streamingQuery = useQuery<boolean>({
    queryKey: ['ui', 'streaming'],
    queryFn: () => false,
    initialData: false,
    staleTime: Infinity,
  });
  const streaming = streamingQuery.data ?? false;
  const setStreaming = useCallback(
    (b: boolean) => {
      qc.setQueryData(['ui', 'streaming'], b);
    },
    [qc],
  );

  // —— Shared writes (mutations through server) ——————————————————————

  // `defaultModel` (the sidebar's selected default — already declared
  // above from `auth.user.preferences.default_model`) is written here via
  // `setDefaultModel`. The sidebar's picker and Settings' "Default model"
  // picker both call this; the server PATCH invalidates the auth query
  // and every useAuth consumer re-renders with the new value.
  //
  // `model` (declared below) is the *current selection* — what `send()`
  // actually uses for the next message. It lives in local state and is
  // initialized from `defaultModel` via the effect below. Picking in
  // ChatInput only affects `model`, not `defaultModel`. Refreshing the
  // page resets the selection back to `defaultModel`.
  const setDefaultModel = useCallback((m: string) => {
    void api.updateMyPreferences({ default_model: m || null }).catch(() => {
      // Auth failures (401) are caught by the global authGuard; other
      // failures don't have a good surface here.
    });
  }, []);

  // `mode` is a single source (server default). Both ChatInput and the
  // Settings "Default mode" picker write to `default_mode`.
  const setMode = useCallback((m: AgentMode) => {
    void api.updateMyPreferences({ default_mode: m }).catch(() => {});
  }, []);

  // —— Per-page state (only ChatPage / ChatInput read these) —————————

  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState('');
  const [model, setModel] = useState('');

  // Reset transient state on logout.
  useEffect(() => {
    if (auth.isReady && !auth.user) {
      qc.removeQueries({
        queryKey: [
          ['chat', 'sessions'],
          ['api', 'health'],
          ['chat', 'models'],
          ['chat', 'connectivity'],
          ['ui', 'error'],
          ['ui', 'streaming'],
        ],
      });
      setTurns([]);
      setInput('');
      setError(null);
    }
  }, [auth.isReady, auth.user, qc]);

  // Initialize `model` from `defaultModel` once the auth query has populated
  // the user's server-side preferences. We only set `model` if it's still
  // empty so a manual pick in ChatInput is preserved across re-renders.
  useEffect(() => {
    if (!defaultModel) return;
    if (model) return;
    setModel(defaultModel);
  }, [defaultModel, model]);

  // When the user clicks the LLM pill, force-refresh the connectivity
  // probe (the useQuery cache updates for all observers).
  const probeConnectivity = useCallback(async () => {
    if (!auth.user) return null;
    const res = await refetchConnectivity();
    const data = res.data;
    if (data && !data.ok) {
      setError(`${data.provider} failed: ${data.error}`);
    }
    return data ?? null;
  }, [auth.user, refetchConnectivity]);

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

  const newSession = useCallback(() => {
    // Navigate to the empty chat route without creating a session row.
    // The session is created lazily by send() when the user actually sends
    // the first message — this avoids littering the sidebar with empty
    // sessions when "+ New chat" is clicked multiple times in a row.
    navigate('/chat');
  }, [navigate]);

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

    const probe = await probeConnectivity();
    if (!probe || !probe.ok) return;

    let sessionId = currentSessionId;
    if (!sessionId) {
      try {
        const created = await api.createSession(undefined, model || undefined);
        sessionId = created.id;
        // Optimistic insert into the shared session cache so the sidebar
        // shows the new session immediately (without waiting for a
        // refetch round-trip). Background refetch via invalidateQueries
        // will reconcile the title with the server's LLM-refined version.
        qc.setQueryData<ChatSession[]>(['chat', 'sessions'], (prev) => [
          created,
          ...(prev ?? []),
        ]);
        void qc.invalidateQueries({ queryKey: ['chat', 'sessions'] });
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
      // Refetch the session list so the sidebar picks up the LLM-refined
      // title (only for first messages ≥ 30 chars).
      void qc.invalidateQueries({ queryKey: ['chat', 'sessions'] });
    } catch (err) {
      setError((err as Error).message);
      setTurns((prev) =>
        prev.map((t) => (t.id === tempTurnId ? { ...t, status: 'error' } : t)),
      );
    } finally {
      streamingRef.current = false;
      setStreaming(false);
    }
  }, [currentSessionId, input, streaming, model, mode, probeConnectivity, navigate, qc]);

  const stop = useCallback(() => {
    // Streaming cannot be aborted yet without an AbortController on the
    // underlying fetch. The stream will run to completion. Future work.
  }, []);

  const removeSession = useCallback(
    async (id: string) => {
      try {
        await api.deleteSession(id);
        // Optimistic remove from the shared session cache so both
        // AppShell and ChatPage see the sidebar update.
        qc.setQueryData<ChatSession[]>(['chat', 'sessions'], (prev) =>
          (prev ?? []).filter((s) => s.id !== id),
        );
        if (id === currentSessionId) {
          navigate('/chat');
        }
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [currentSessionId, navigate, qc],
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
    defaultModel,
    setDefaultModel,
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