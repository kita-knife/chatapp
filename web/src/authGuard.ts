/**
 * Global 401 (session-expired) handler.
 *
 * When the backend invalidates a session — typically because root changed
 * the user's password, or because root deleted the user, or because the
 * session token simply expired — every subsequent API call returns 401.
 * Without this hook, the webapp would keep showing the protected UI
 * because the auth-status query is cached (staleTime: 30s) and individual
 * error handlers only show a banner — they never log the user out.
 *
 * Wiring: `App.tsx` calls `setQueryClient(queryClient)` at module load
 * (before the router is rendered). We hook into the QueryCache +
 * MutationCache event streams to detect every error and react to 401s
 * that come from a session-protected endpoint while we're NOT on the
 * login page.
 *
 * Earlier version used `useNavigate()` from a top-level App component,
 * which threw at runtime because useNavigate must be called inside a
 * <Router>. This version uses the imperative `router.navigate()`
 * method on the module-level `router` instance, which has no React
 * context dependency.
 *
 * Endpoints that are allowed to return 401 without triggering a logout:
 *   - /api/auth/login    (wrong password is a normal failure)
 *   - /api/auth/status   (anonymous request, always allowed)
 *   - /api/auth/logout   (already-logged-out case)
 */
import type { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';
import { ApiError } from './api/client';
import { router } from './app/router';
import { setAuthErrorHandler } from '@/authEvents';

let queryClientRef: QueryClient | null = null;

/** Register the QueryClient the guard will manage. Idempotent. */
export function setQueryClient(qc: QueryClient): void {
  queryClientRef = qc;
}

/** Paths whose 401 is normal — must not trigger global logout. */
function isAuthEndpoint(path: string): boolean {
  return (
    path.startsWith('/api/auth/login') ||
    path.startsWith('/api/auth/status') ||
    path.startsWith('/api/auth/logout')
  );
}

/** True when the browser is already on the login page (avoid redirect loops). */
function isOnLoginPage(): boolean {
  return typeof window !== 'undefined' && window.location.pathname === '/login';
}

/** Force a global logout: clear cache + navigate to /login.
 *
 * Debounced via the `loggingOut` flag because several in-flight queries
 * typically fail with 401 at the same instant (the user lands on a
 * protected route and every observer fires its query in parallel).
 * Without the debounce, each 401 would re-clear the cache, which
 * triggers re-renders that re-fire the same queries, which get 401
 * again — a feedback loop that strands buttons in their `isPending`
 * state for a couple of seconds before the loop converges.
 *
 * The flag also releases the `isPending` state of in-flight mutations
 * by calling `cancelQueries()` BEFORE clearing the cache — without
 * this, the cancel only happens implicitly via component unmount.
 */
let loggingOut = false;

function forceLogout(): void {
  if (loggingOut) return;
  loggingOut = true;

  if (queryClientRef) {
    // Abort in-flight fetches so mutations release their pending state.
    queryClientRef.cancelQueries();
    // Then drop cached data so observers re-render with `user: null`
    // and ProtectedRoute redirects to /login.
    queryClientRef.clear();
  }
  try {
    router.navigate('/login');
  } catch {
    // router.navigate() can throw if called before RouterProvider mounted.
    // Fall back to a hard navigation in that edge case.
    window.location.assign('/login');
  }

  // Reset the flag after a few seconds so that legitimate future 401s
  // (e.g. after the user logs back in and that session also expires)
  // can trigger another logout cycle.
  setTimeout(() => {
    loggingOut = false;
  }, 3000);
}

/** Inspect an unknown error and decide whether to log the user out. */
function shouldForceLogout(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false;
  if (err.status !== 401) return false;
  if (isAuthEndpoint(err.path)) return false;
  if (isOnLoginPage()) return false;
  return true;
}

let installed = false;

/**
 * Subscribe to query + mutation error events for the registered
 * QueryClient. When an event signals a 401 from a session-protected
 * endpoint while we're not on /login, force a global logout.
 *
 * Idempotent: calling this twice is a no-op (the `installed` flag
 * prevents double subscription). Safe under React StrictMode because
 * we register exactly once at module import time — there is no React
 * useEffect to be double-invoked.
 */
export function setupGlobal401Handler(): void {
  if (installed || !queryClientRef) return;
  installed = true;

  const handle = (err: unknown) => {
    if (shouldForceLogout(err)) {
      forceLogout();
    }
  };

  const queryCache: QueryCache = queryClientRef.getQueryCache();
  queryCache.subscribe((event) => {
    if (event.type === 'updated') {
      const query = event.query;
      if (query.state.status === 'error') {
        handle(query.state.error);
      }
    }
  });

  const mutationCache: MutationCache = queryClientRef.getMutationCache();
  mutationCache.subscribe((event) => {
    if (event.type === 'updated') {
      const mutation = event.mutation;
      if (mutation.state.isPaused) return;
      const status = mutation.state.status;
      if (status === 'error') {
        handle(mutation.state.error);
      }
    }
  });

  // Catch 401s from raw `fetch` calls that bypass TanStack Query
  // (e.g. the `send` button's `probeConnectivity`, the `+ New chat`
  // session create). Without this hook, only paths that go through
  // useQuery / useMutation would surface here — settings did, send didn't.
  setAuthErrorHandler((err) => {
    handle(err);
  });
}