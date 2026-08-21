/**
 * Typed API client generated from FastAPI's OpenAPI schema.
 *
 * Uses openapi-fetch for type-safe requests.
 * Types are generated via `npm run codegen` from /api/openapi.json.
 *
 * In development, Next.js proxies /api/* to the FastAPI backend (see next.config.ts).
 * In production, same-origin deployment means no proxy is needed.
 */

import createClient from "openapi-fetch";
import type { paths } from "@/generated/api";

/**
 * Origen al que apunta el cliente tipado.
 *
 * En navegador se usa el propio origen y no la cadena vacía. `openapi-fetch`
 * no llama a `fetch(url, init)`: construye un `new Request(url, init)` y le
 * pasa el objeto. La implementación de `Request` de Node —la que corre bajo
 * jsdom en los tests— rechaza las URLs relativas (`TypeError: Failed to parse
 * URL from /api/v1/…`), así que con `baseUrl: ""` toda llamada por este
 * cliente reventaba en cuanto se ejercitaba desde un test. Al ser el mismo
 * origen, en el navegador la request resultante es idéntica a la relativa.
 */
function resolveBaseUrl(): string {
  if (typeof window !== "undefined") return window.location.origin;
  // fdi-allow:localhost-url — fallback SSR/Node legítimo cuando API_BASE_URL no está set; no es dato renderizado.
  return process.env.API_BASE_URL ?? "http://localhost:8080";
}

/**
 * Base API client — all requests go through this.
 * Cookie-based auth (httpOnly) is handled automatically by the browser.
 */
export const api = createClient<paths>({
  baseUrl: resolveBaseUrl(),
  /**
   * `openapi-fetch` captura `globalThis.fetch` una sola vez, al crear el
   * cliente. Como este módulo se evalúa al importarlo, esa captura ocurre
   * antes de que un test pueda sustituir el global, y el doble nunca se
   * usaba. Resolverlo en cada llamada mantiene el fetch global sustituible,
   * igual que en `fetchWithAuth` — sin cambiar nada en producción.
   */
  fetch: (request) => globalThis.fetch(request),
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
  },
});

/**
 * Redirige a /login preservando el deep-link actual como `?redirect=`, igual
 * que el middleware de Next (`web/src/middleware.ts`). No hace nada en SSR ni
 * si ya estamos en /login (evita un bucle de redirecciones y perder el destino).
 */
function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/login") return;
  const destino = window.location.pathname + window.location.search;
  window.location.href = `/login?redirect=${encodeURIComponent(destino)}`;
}

/**
 * Global middleware: redirect to login on 401 responses.
 * Centralizes auth expiry handling for all API calls via the typed client.
 */
api.use({
  onResponse({ response }) {
    if (response.status === 401 && typeof window !== "undefined") {
      redirectToLogin();
    }
    return undefined;
  },
});

/**
 * Helper to get CSRF token from cookie (set by the API on login).
 * Include this in mutation requests (POST/PUT/DELETE).
 */
export function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Fetch wrapper that includes CSRF token for mutations.
 */
/**
 * Rutas donde un 401 es la respuesta normal del flujo, no una sesión caducada.
 *
 * Sin esta distinción, escribir mal la contraseña disparaba el `window.
 * location.href = "/login"` de abajo: el navegador recargaba /login, el
 * componente se destruía antes de pintar nada y el usuario veía la pantalla
 * parpadear sin ningún mensaje. El `setError("Credenciales incorrectas")` del
 * formulario sí se ejecutaba — no llegaba a verse. Lo detectó el E2E al
 * comprobar que un intento fallido muestra el error.
 */
const RUTAS_CON_401_ESPERADO = ["/auth/login", "/auth/register", "/auth/totp/verify"];

function esRespuestaEsperada401(url: string): boolean {
  return RUTAS_CON_401_ESPERADO.some((ruta) => url.includes(ruta));
}

export async function apiMutate<T>(
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  url: string,
  body?: unknown,
): Promise<T> {
  const csrf = getCsrfToken();
  const res = await fetch(url, {
    method,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined" && !esRespuestaEsperada401(url)) {
      redirectToLogin();
      throw new ApiError(401, "Session expired");
    }
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, error.detail ?? error.title ?? "Unknown error");
  }

  return res.json() as Promise<T>;
}

/**
 * Lightweight fetch wrapper that uses the same auth pattern as the typed client.
 * Use this for dynamic URLs that can't use the typed openapi-fetch client.
 * 401 handling is done centrally here — no need to duplicate in callers.
 *
 * CSRF: si `options.method` es una mutación (POST/PUT/PATCH/DELETE), se
 * adjunta `X-CSRF-Token` igual que `apiMutate` — hasta 2026-08 cualquier
 * mutación enrutada por aquí viajaba sin token y el backend la rechazaba (o
 * peor: pasaba solo por autenticarse con API key en vez de cookie).
 */
export async function fetchWithAuth<T>(
  url: string,
  options?: RequestInit,
): Promise<T> {
  const method = (options?.method ?? "GET").toUpperCase();
  const isMutation = method !== "GET" && method !== "HEAD";
  const csrf = isMutation ? getCsrfToken() : null;
  const res = await fetch(url, {
    credentials: "include",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...(options?.headers ?? {}),
    },
  });

  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") {
      redirectToLogin();
    }
    // La API responde `application/problem+json` (RFC 7807): `detail` es el
    // mensaje y `title` el genérico. Los cortes de middleware (429, 413) solo
    // garantizan `title`, así que se usa como respaldo.
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? body.title ?? `API error: ${res.status}`);
  }

  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Rutas GET del esquema generado. Es el conjunto de literales que la API
 * declara, así que un typo o un endpoint retirado no compila.
 */
export type ApiGetPath = keyof {
  [P in keyof paths as paths[P] extends { get: unknown } ? P : never]: paths[P];
};

/**
 * GET tipado contra el esquema OpenAPI generado.
 *
 * Por qué existe: hasta 2026-08 el cliente tipado (`api`, arriba) no tenía un
 * solo call site. Las ~90 llamadas iban por `fetchWithAuth` con URLs literales
 * y cerraban con `res.json() as Promise<T>` — un cast, no una validación. El
 * resultado es que `web/src/generated/api.d.ts` y el job de CI que lo custodia
 * contra drift no protegían ninguna línea de producto: un endpoint que cambia
 * de forma o de ruta compilaba igual y rompía en runtime.
 *
 * Con este helper la ruta se comprueba contra el esquema y el tipo de retorno
 * sale de él, en vez de escribirse a mano en el hook.
 *
 * Las llamadas con ruta dinámica (`/licitaciones/{id}`) siguen usando
 * `fetchWithAuth`; para esas, tipá el retorno con `components["schemas"][...]`
 * vía `@/lib/api-types`, nunca con una interfaz local.
 *
 * Migración por olas: `src/hooks/**` ya está migrado; `src/app/**`,
 * `src/components/**` y `src/lib/**` siguen pendientes.
 */
export type ApiGetResult<P extends ApiGetPath> = paths[P] extends {
  get: { responses: { 200: { content: { "application/json": infer R } } } };
}
  ? R
  : never;

/**
 * Valor admisible en un parámetro de query.
 *
 * `undefined` y `null` los descarta el serializador de `openapi-fetch`, así que
 * un filtro sin valor no llega a la URL: es el equivalente al `if (x) params.
 * set(...)` que hacían los hooks a mano.
 */
export type ApiQueryValue = string | number | boolean | readonly string[] | null | undefined;

export async function apiGet<P extends ApiGetPath>(
  path: P,
  init?: { params?: { query?: Record<string, ApiQueryValue> }; signal?: AbortSignal },
): Promise<ApiGetResult<P>> {
  const { data, error, response } = await (
    api.GET as unknown as (
      p: P,
      o?: Record<string, unknown>,
    ) => Promise<{ data?: unknown; error?: unknown; response: Response }>
  )(path, { params: init?.params, signal: init?.signal });

  if (error !== undefined || !response.ok) {
    const problem = (error ?? {}) as { detail?: string; title?: string };
    throw new ApiError(
      response.status,
      problem.detail ?? problem.title ?? `API error: ${response.status}`,
    );
  }
  return data as ApiGetResult<P>;
}
