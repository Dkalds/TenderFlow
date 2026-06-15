/**
 * Centralized toast feedback for React Query.
 *
 * Wired once in `providers.tsx` via QueryCache/MutationCache so every query and
 * mutation in the app surfaces failures (and mutation successes) consistently,
 * without each call site repeating toast logic.
 *
 * Opt out or customize per query/mutation through `meta` (see QueryFeedbackMeta).
 */
import { toast } from "sonner";
import { ApiError } from "@/lib/api-client";

/** Meta flags recognized by the global query/mutation feedback handlers. */
export interface QueryFeedbackMeta extends Record<string, unknown> {
  /** Suppress the automatic error toast for this query/mutation. */
  silent?: boolean;
  /** Headline for the error toast (e.g. "No se pudo guardar el filtro"). */
  errorTitle?: string;
  /** Toast shown when a mutation succeeds. */
  successMessage?: string;
}

/** Human-friendly message for any thrown error. */
export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) return "Error del servidor. Inténtalo de nuevo en unos segundos.";
    return error.message || "No se pudo completar la solicitud.";
  }
  if (error instanceof Error) {
    if (error.message === "Failed to fetch") return "Sin conexión con el servidor.";
    return error.message;
  }
  return "Ocurrió un error inesperado.";
}

/** Errors already resolved by a redirect (auth expiry) — no toast needed. */
function isAuthError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export function notifyQueryError(error: unknown, meta?: QueryFeedbackMeta): void {
  if (meta?.silent || isAuthError(error)) return;
  toast.error(meta?.errorTitle ?? "Error al cargar datos", {
    description: getErrorMessage(error),
  });
}

export function notifyMutationError(error: unknown, meta?: QueryFeedbackMeta): void {
  if (meta?.silent || isAuthError(error)) return;
  toast.error(meta?.errorTitle ?? "La acción no se pudo completar", {
    description: getErrorMessage(error),
  });
}

export function notifyMutationSuccess(meta?: QueryFeedbackMeta): void {
  if (meta?.successMessage) toast.success(meta.successMessage);
}
