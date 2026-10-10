/**
 * Opciones de Sentry comunes al navegador (`src/instrumentation-client.ts`) y
 * al servidor (`sentry.server.config.ts`).
 *
 * **Es opt-in por `NEXT_PUBLIC_SENTRY_DSN`**, igual que el backend lo es por
 * `SENTRY_DSN` (`observability/sentry.py`): sin la variable no se llama a
 * `init` y el SDK no instala nada. Es el estado de un build local, del job
 * `frontend` de CI y del E2E. En Vercel la pone la integración de Sentry del
 * Marketplace, en preview y en producción.
 *
 * **Qué no sale de aquí**, y es la misma regla que ya sigue el canal propio
 * (`lib/report-error.ts`):
 *
 * - La query string. El ámbito de una pantalla vive ahí y lleva nombres de
 *   empresa e identificadores; se recorta de la URL del evento, del `Referer` y
 *   de las migas de navegación y de red.
 * - Cookies y cuerpo de la petición, y de las cabeceras todas menos tres
 *   (`host`, `user-agent` y `referer`). Es una lista de las que pasan y no de
 *   las que se quitan: en servidor el evento trae las de la petición entera,
 *   y ahí vienen la IP del visitante (`x-forwarded-for`), su geolocalización
 *   (`x-vercel-ip-*`) y el nonce de la CSP. Una lista de vetadas se queda
 *   corta el día que la plataforma añade una.
 * - Del usuario, todo menos un `id` opaco: ni email, ni nombre, ni IP
 *   (`sendDefaultPii: false` ya evita que el SDK los ponga; el recorte cubre a
 *   quien llame a `setUser` con más de la cuenta).
 * - Las migas de `console`: por ahí pasan los objetos arbitrarios que
 *   `reportError` se niega a enviar como `extra`.
 *
 * Solo errores (el servidor añade el recuento agregado de peticiones por
 * versión que el SDK llama *release health*; no lleva dato de visitante). Sin
 * trazas de rendimiento —sus spans llevan la URL completa de
 * cada `fetch`, query incluida, y recortarlas es otro trabajo— y sin Session
 * Replay, que graba la pantalla y es una decisión de privacidad, no de
 * configuración.
 */
import type { Breadcrumb, ErrorEvent } from "@sentry/nextjs";

export const SENTRY_DSN = process.env.NEXT_PUBLIC_SENTRY_DSN?.trim() || undefined;

/**
 * Ruta propia por la que el navegador manda los eventos; Next la reescribe al
 * ingest de Sentry (`tunnelRoute` en `next.config.ts`). Es lo que deja la CSP
 * en `connect-src 'self'` y lo que evita que un bloqueador de anuncios se
 * coma los reportes.
 *
 * El matcher de `src/proxy.ts` la excluye con el literal escrito a mano —Next
 * exige que sea estático— y `__tests__/proxy.test.ts` comprueba que coinciden.
 */
export const RUTA_TUNEL_SENTRY = "/monitoring";

const CABECERAS_PERMITIDAS = new Set(["host", "user-agent", "referer"]);

/** La URL sin query ni fragmento. */
export function sinQuery(url: string): string {
  return url.replace(/[?#].*$/, "");
}

export function limpiarEvento(event: ErrorEvent): ErrorEvent {
  const { request, user } = event;
  if (request) {
    if (request.url) request.url = sinQuery(request.url);
    delete request.query_string;
    delete request.cookies;
    delete request.data;
    if (request.headers) {
      for (const nombre of Object.keys(request.headers)) {
        const clave = nombre.toLowerCase();
        if (!CABECERAS_PERMITIDAS.has(clave)) delete request.headers[nombre];
        else if (clave === "referer") request.headers[nombre] = sinQuery(request.headers[nombre]);
      }
    }
  }
  if (user) event.user = user.id === undefined ? {} : { id: user.id };
  // El SDK de Next apunta aquí la ruta pedida al servidor, con su query.
  const next = event.contexts?.nextjs;
  if (next && typeof next.request_path === "string") next.request_path = sinQuery(next.request_path);
  return event;
}

const CAMPOS_CON_URL = ["url", "from", "to"] as const;

export function limpiarMiga(miga: Breadcrumb): Breadcrumb | null {
  if (miga.category === "console") return null;
  if (miga.data) {
    for (const campo of CAMPOS_CON_URL) {
      const valor: unknown = miga.data[campo];
      if (typeof valor === "string") miga.data[campo] = sinQuery(valor);
    }
  }
  return miga;
}

export const OPCIONES_SENTRY = {
  dsn: SENTRY_DSN,
  sendDefaultPii: false,
  beforeSend: limpiarEvento,
  beforeBreadcrumb: limpiarMiga,
};
