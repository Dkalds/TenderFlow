/**
 * Centralized toast feedback for React Query.
 *
 * Wired once in `providers.tsx` via QueryCache/MutationCache so every query and
 * mutation in the app surfaces failures (and mutation successes) consistently,
 * without each call site repeating toast logic.
 *
 * Opt out or customize per query/mutation through `meta` (see QueryFeedbackMeta).
 *
 * Aquí vive también la política de reintentos (`debeReintentar` /
 * `retrasoDeReintento`), porque decidir *si un error merece otro intento* y
 * decidir *qué se le cuenta al usuario* son la misma clasificación: "el
 * servidor no respondió" frente a "el servidor respondió que no".
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

/**
 * Mensajes con los que el navegador reporta que la conexión ni llegó a
 * establecerse. Varían por motor (Chrome/Firefox: "Failed to fetch" o
 * "NetworkError…", Safari: "Load failed", undici en Node: "fetch failed"), así
 * que no se puede depender de uno solo.
 */
const MENSAJES_DE_RED = ["failed to fetch", "networkerror", "load failed", "fetch failed"];

/**
 * ¿El error significa "no hubo respuesta" en vez de "la respuesta fue que no"?
 *
 * La API corre en Render con spin-down (plan free, ver `render.yaml`): tras un
 * rato de inactividad la instancia está apagada y el primer request paga un
 * arranque en frío de decenas de segundos, que llega al frontend como un fallo
 * de red o como el 502/504 del proxy. Eso *sí* merece otro intento, porque el
 * servidor está literalmente en camino. Un 400/403/404/409 es una respuesta
 * deliberada del backend: repetirla da exactamente el mismo resultado, así que
 * reintentarla solo retrasa el mensaje de error.
 */
export function esErrorTransitorio(error: unknown): boolean {
  if (error instanceof ApiError) {
    // 429 queda fuera a propósito: es el rate-limit del middleware diciendo
    // "menos peticiones", y reintentar es lo contrario de obedecerlo.
    return error.status === 408 || error.status >= 500;
  }
  if (error instanceof Error) {
    // Una petición cancelada (cambio de filtro, desmontaje) no es un fallo.
    if (error.name === "AbortError") return false;
    const mensaje = error.message.toLowerCase();
    return MENSAJES_DE_RED.some((fragmento) => mensaje.includes(fragmento));
  }
  return false;
}

/** Reintentos máximos para un error transitorio (5 intentos en total). */
export const MAX_REINTENTOS_TRANSITORIOS = 4;
const RETRASO_BASE_MS = 1000;
/** Tope por reintento: el backoff crece, pero no hasta esperas absurdas. */
const RETRASO_MAX_MS = 8000;

/**
 * `retry` de React Query.
 *
 * `failureCount` llega en **0** en el primer fallo, no en 1: query-core evalúa
 * `retry(failureCount, error)` *antes* de incrementarlo (ver
 * `@tanstack/query-core/build/modern/retryer.js`, `createRetryer`). Es el mismo
 * índice que recibe `retrasoDeReintento`, así que los dos comparten origen y el
 * presupuesto de espera se puede sumar leyéndolos juntos.
 *
 * De ahí el `<` y no el `<=`: con el tope en 4 salen 4 reintentos (5 intentos
 * contando el original) y 1+2+4+8 = 15 s de espera. El `<=` que había aquí
 * dejaba pasar `failureCount` 0..4 — 5 reintentos y 23 s — o sea la mitad más
 * de spinner del que la política dice presupuestar antes de rendirse y avisar.
 */
export function debeReintentar(failureCount: number, error: unknown): boolean {
  return esErrorTransitorio(error) && failureCount < MAX_REINTENTOS_TRANSITORIOS;
}

/**
 * `retryDelay` de React Query: backoff exponencial 1s → 2s → 4s → 8s (`intento`
 * empieza en 0, igual que el `failureCount` de `debeReintentar`). Suma 15s de
 * espera antes de darse por vencido, que es el orden de magnitud de un arranque
 * en frío sin ser una eternidad delante de una pantalla que no dice nada — por
 * eso existe la banda de reconexión.
 */
export function retrasoDeReintento(intento: number): number {
  return Math.min(RETRASO_BASE_MS * 2 ** intento, RETRASO_MAX_MS);
}

/**
 * Ventana en la que varios fallos se consideran **el mismo incidente**.
 *
 * La pantalla de Resumen dispara ~28 peticiones por carga. Con un toast por
 * query fallida, un arranque en frío pintaba una cascada de ~28 toasts rojos
 * idénticos, que es justo la lectura "la aplicación está rota" en vez de "el
 * servidor tardó en despertar". Se agrupan por causa y se colapsan en un único
 * toast (mismo `id` de Sonner ⇒ se actualiza en sitio, no se apila).
 */
const VENTANA_DE_AGRUPACION_MS = 4000;

interface IncidenteAbierto {
  /** Cuántas queries han fallado por esta misma causa dentro de la ventana. */
  veces: number;
  abiertoEn: number;
}

const incidentes = new Map<string, IncidenteAbierto>();

/**
 * Clave de agrupación. Dos 404 de endpoints distintos son dos problemas
 * distintos y siguen avisando por separado; en cambio todo lo transitorio cae
 * en el mismo cubo, porque en un arranque en frío la causa es una sola por
 * mucho que la reporten 28 peticiones.
 */
function claveDeIncidente(error: unknown, titulo: string): string {
  if (esErrorTransitorio(error)) return `${titulo}|sin-respuesta`;
  if (error instanceof ApiError) return `${titulo}|api-${error.status}|${error.message}`;
  return `${titulo}|${getErrorMessage(error)}`;
}

/** Registra el fallo y devuelve cuántos van en la ventana vigente (>= 1). */
function registrarIncidente(clave: string): number {
  const ahora = Date.now();
  for (const [otraClave, incidente] of incidentes) {
    if (ahora - incidente.abiertoEn > VENTANA_DE_AGRUPACION_MS) incidentes.delete(otraClave);
  }
  const abierto = incidentes.get(clave);
  if (!abierto) {
    incidentes.set(clave, { veces: 1, abiertoEn: ahora });
    return 1;
  }
  abierto.veces += 1;
  return abierto.veces;
}

/**
 * Reinicia la agrupación. Solo para tests: en el navegador la ventana caduca
 * sola y el módulo vive lo que vive la pestaña.
 */
export function reiniciarAgrupacionDeAvisos(): void {
  incidentes.clear();
}

/**
 * Qué se le dice al usuario cuando el servidor no contestó.
 *
 * No promete nada: cuando este toast aparece los reintentos ya se agotaron. El
 * mensaje describe lo que pasó, no lo que va a pasar.
 */
function descripcionDeIncidente(error: unknown, veces: number): string {
  const base = esErrorTransitorio(error)
    ? "No hubo respuesta tras varios reintentos. Vuelve a intentarlo en unos segundos."
    : getErrorMessage(error);
  return veces > 1 ? `${base} (${veces} peticiones afectadas)` : base;
}

export function notifyQueryError(error: unknown, meta?: QueryFeedbackMeta): void {
  if (meta?.silent || isAuthError(error)) return;
  const titulo = meta?.errorTitle ?? (esErrorTransitorio(error) ? "El servidor no responde" : "Error al cargar datos");
  const clave = claveDeIncidente(error, titulo);
  toast.error(titulo, {
    // `id` estable por causa: Sonner reemplaza el toast existente en vez de
    // apilar uno nuevo, así que N fallos simultáneos son un aviso, no N.
    id: clave,
    description: descripcionDeIncidente(error, registrarIncidente(clave)),
  });
}

/**
 * Las mutaciones **no** se agrupan ni se reintentan: cada una es una acción que
 * el usuario pidió de una en una (y repetir un POST no es inocuo). El aviso
 * individual es aquí la respuesta correcta, no un problema de volumen.
 */
export function notifyMutationError(error: unknown, meta?: QueryFeedbackMeta): void {
  if (meta?.silent || isAuthError(error)) return;
  toast.error(meta?.errorTitle ?? "La acción no se pudo completar", {
    description: getErrorMessage(error),
  });
}

export function notifyMutationSuccess(meta?: QueryFeedbackMeta): void {
  if (meta?.successMessage) toast.success(meta.successMessage);
}
