/**
 * Lectura de las llamadas a `fetch` en los tests de hooks.
 *
 * Desde la migración al cliente tipado conviven dos formas de invocar `fetch`
 * en el mismo hook:
 *
 *  - `fetchWithAuth` / `apiMutate` llaman `fetch(url, init)` — la URL es la
 *    cadena relativa y el método viaja en `init`.
 *  - `apiGet` va por `openapi-fetch`, que construye un `new Request(url, init)`
 *    y llama `fetch(request)`. Ahí no hay `init`, la URL es absoluta y
 *    `String(call[0])` devuelve `"[object Request]"`.
 *
 * Estos helpers normalizan ambas para que las aserciones sigan hablando de
 * ruta y método, no de la forma que tenga la llamada por dentro.
 */

/** Ruta + query de la llamada, siempre relativa al origen. */
export function callUrl(call: readonly unknown[]): string {
  const input = call[0];
  const raw = input instanceof Request ? input.url : String(input);
  if (!/^https?:\/\//.test(raw)) return raw;
  const parsed = new URL(raw);
  return `${parsed.pathname}${parsed.search}`;
}

/** Método HTTP en mayúsculas (`GET` cuando no se especifica ninguno). */
export function callMethod(call: readonly unknown[]): string {
  const input = call[0];
  if (input instanceof Request) return input.method.toUpperCase();
  const init = call[1] as RequestInit | undefined;
  return (init?.method ?? "GET").toUpperCase();
}

/** Modo de credenciales, para comprobar que la cookie de sesión viaja. */
export function callCredentials(call: readonly unknown[]): string | undefined {
  const input = call[0];
  if (input instanceof Request) return input.credentials;
  return (call[1] as RequestInit | undefined)?.credentials;
}

/** Respuesta JSON real (no un doble): `openapi-fetch` lee `headers` y `text()`. */
export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
