/**
 * Chat state hook. The URL (`/chat/:sessionId`) is the single source of truth
 * for which session is active — `currentSessionId` is derived from
 * `useParams()`. All actions either create a new session (and navigate) or
 * navigate to an existing one.
 *
 * Shared state (read by both AppShell and ChatPage) lives in TanStack
 * Query's singleton cache so the two useChat instances see the same data.
 * Per-page state (input, turns, currentSessionId) stays local.
 *
 * Default selections (language, mode, model) all live in `user_preferences`
 * on the server. The dropdowns in ChatInput are the only writers: each
 * `onChange` PATCHes `/api/auth/me/preferences`, the auth query invalidates,
 * and `useChat` consumers re-render with the new value. This is the only
 * source of truth — there is no parallel local state for these.
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
import { useUpdateMyPreferences } from '@/features/auth/useAuth';
import type { AgentMode, UiLanguage } from '@/components/ChatInput';

// How long a connectivity-probe failure stays in the error banner before
// auto-dismissing. Manual probes shouldn't leave a permanent "LLM ✗" toast
// when the user just clicks the LLM pill to re-check.
const PROBE_ERROR_DISMISS_MS = 3000;

export function useChat() {
  const navigate = useNavigate();
  const auth = useAuth();
  const logout = useLogout();
  const updateMyPreferences = useUpdateMyPreferences();
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

  // Models list — AppShell's picker, ChatInput's picker.
  const modelsQuery = useQuery<ModelInfo[]>({
    queryKey: ['chat', 'models'],
    queryFn: () => api.listModels(),
    enabled: !!auth.user,
    staleTime: 5 * 60_000,
  });
  const models = modelsQuery.data ?? [];

  // Available graph projects (for the project dropdown). Cached for the
  // session since they only change when the underlying graph_folders table
  // is reloaded (rare).
  const projectsQuery = useQuery<string[]>({
    queryKey: ['chat', 'projects'],
    queryFn: () => api.listProjects(),
    enabled: !!auth.user,
    staleTime: 5 * 60_000,
  });
  const projects = projectsQuery.data ?? [];

  // Default selections — single source of truth (server-backed).
  // `model` is the dropdown's value AND the value send() uses; there is no
  // separate "current selection" anymore. Backend's `get_preferences()`
  // resolves null `default_model` to `settings.openlike_model`, so `model`
  // is always a concrete identifier the dropdown can render.
  const model = auth.user?.preferences?.default_model ?? '';
  const mode: AgentMode =
    (auth.user?.preferences?.default_mode as AgentMode | undefined) ?? 'simple';
  const uiLanguage: UiLanguage =
    (auth.user?.preferences?.ui_language as UiLanguage | undefined) ?? 'zh';
  const project = auth.user?.preferences?.default_project ?? '';

  // Connectivity probe — keyed on `model`, so picking a new dropdown
  // value automatically triggers a refetch against the new model.
  const connectivityQuery = useQuery<ConnectivityResult | null>({
    queryKey: ['chat', 'connectivity', model || ''],
    queryFn: () => api.connectivity(model || undefined),
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
  //
  // Each setter below is the *only* writer for its preference key. We use
  // the `useUpdateMyPreferences` mutation (not the raw `api.updateMyPreferences`)
  // because the mutation's `onSuccess` invalidates the `auth` query —
  // without that, `auth.user.preferences.*` stays stale, the dropdowns
  // bound to `model` / `mode` / `uiLanguage` won't reflect the new value,
  // and the connectivity probe (keyed on `model`) won't refetch.
  //
  // Mutations are fire-and-forget here; errors land in `updateMyPreferences.error`
  // and surface via the auth guard for 401s. Other failures don't have a
  // dedicated UI surface yet — same trade-off as before.

  const setModel = useCallback(
    (m: string) => {
      updateMyPreferences.mutate({ preferences: { default_model: m || null } });
    },
    [updateMyPreferences],
  );

  const setMode = useCallback(
    (m: AgentMode) => {
      updateMyPreferences.mutate({ preferences: { default_mode: m } });
    },
    [updateMyPreferences],
  );

  const setLanguage = useCallback(
    (l: UiLanguage) => {
      updateMyPreferences.mutate({ preferences: { ui_language: l } });
    },
    [updateMyPreferences],
  );

  const setProject = useCallback(
    (p: string) => {
      updateMyPreferences.mutate({ preferences: { default_project: p || null } });
    },
    [updateMyPreferences],
  );

  // —— Per-page state (only ChatPage / ChatInput read these) —————————

  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState('');

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
  }, [auth.isReady, auth.user, qc, setError]);

  // When the user clicks the LLM pill, force-refresh the connectivity
  // probe (the useQuery cache updates for all observers). On success we
  // also clear any stale banner error left over from a previous failed
  // probe — otherwise the user sees the last failure's message even after
  // a successful probe. On failure the banner auto-dismisses after a short
  // delay so a transient probe failure doesn't sit on screen forever.
  const probeErrorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (probeErrorTimerRef.current) clearTimeout(probeErrorTimerRef.current);
    },
    [],
  );
  const probeConnectivity = useCallback(async () => {
    if (!auth.user) return null;
    // Cancel any pending auto-dismiss from a previous probe — we'll
    // either schedule a new one (on failure) or clear immediately (on
    // success).
    if (probeErrorTimerRef.current) {
      clearTimeout(probeErrorTimerRef.current);
      probeErrorTimerRef.current = null;
    }
    const res = await refetchConnectivity();
    const data = res.data;
    if (data && !data.ok) {
      setError(`${data.provider} failed: ${data.error}`);
      probeErrorTimerRef.current = setTimeout(() => {
        setError(null);
        probeErrorTimerRef.current = null;
      }, PROBE_ERROR_DISMISS_MS);
    } else if (data && data.ok) {
      setError(null);
    }
    return data ?? null;
  }, [auth.user, refetchConnectivity, setError]);

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
  }, [auth.user, currentSessionId, setError]);

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
      tool_calls: [],
      tool_results: [],
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
      for await (const chunk of api.streamMessage(
        sessionId,
        userContent,
        model || undefined,
        mode,
        project || undefined,
      )) {
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
        if (chunk.tool_call) {
          const tc = chunk.tool_call;
          setTurns((prev) =>
            prev.map((t) =>
              t.id === tempTurnId
                ? { ...t, tool_calls: [...(t.tool_calls ?? []), tc] }
                : t,
            ),
          );
        }
        if (chunk.tool_result) {
          const tr = chunk.tool_result;
          setTurns((prev) =>
            prev.map((t) =>
              t.id === tempTurnId
                ? { ...t, tool_results: [...(t.tool_results ?? []), tr] }
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
  }, [currentSessionId, input, streaming, model, mode, project, probeConnectivity, navigate, qc, setError, setStreaming]);

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
    [currentSessionId, navigate, qc, setError],
  );

  const handleLogout = useCallback(() => {
    logout.mutate(undefined, {
      onSuccess: () => navigate('/login', { replace: true }),
    });
  }, [logout, navigate]);

  return {
    sessions,
    models,
    projects,
    currentSessionId,
    turns,
    input,
    setInput,
    model,
    setModel,
    mode,
    setMode,
    uiLanguage,
    setLanguage,
    project,
    setProject,
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
