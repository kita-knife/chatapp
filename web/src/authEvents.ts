/**
 * Module-level bridge between `api/client.ts` (which makes raw `fetch`
 * calls outside TanStack Query) and `authGuard.ts` (which subscribes to
 * TanStack Query's queryCache / mutationCache events).
 *
 * `api/client.ts` calls `notifyAuthError(err)` whenever it throws an
 * `ApiError(401, …)`. `authGuard.ts` registers a single handler via
 * `setAuthErrorHandler(fn)`; the handler decides whether to force a
 * global logout.
 *
 * This indirection keeps `api/client.ts` and `authGuard.ts` from
 * importing each other (which would be a circular import — client
 * needs `ApiError` to throw, authGuard wants to subscribe).
 */
import type { ApiError } from './api/client';

type Handler = (err: ApiError) => void;
let handler: Handler | null = null;

export function setAuthErrorHandler(fn: Handler | null): void {
  handler = fn;
}

export function notifyAuthError(err: ApiError): void {
  handler?.(err);
}