import { headers } from "next/headers";
import { QueryClient, dehydrate, type DehydratedState, type QueryKey } from "@tanstack/react-query";

/**
 * Prefetch en servidor con hidratación (S5.1 del plan de septiembre, S7.1 del
 * v2).
 *
 * Todas las pantallas del dashboard son `"use client"` y pedían su primer dato
 * **después** de hidratar: HTML con esqueletos, descarga del bundle, hidratación
 * y sólo entonces la primera petición a la API. Con esto el servidor hace esas
 * peticiones mientras renderiza, las vuelca en un `QueryClient` propio de la
 * request y se las pasa al del navegador vía `HydrationBoundary`. Los hooks no
 * cambian: encuentran la clave ya en caché y no piden nada.
 *
 * Tres reglas que no son opcionales:
 *
 * 1. **La clave tiene que ser idéntica a la del hook.** Por eso las claves se
 *    construyen con los mismos módulos puros que usa el cliente
 *    (`lib/filtered-query.ts`, `lib/filter-params.ts`, `lib/query-keys.ts`),
 *    nunca escritas a mano aquí. Y el `transformar` de cada consulta tiene que
 *    hacer lo mismo que el `queryFn` del hook (p. ej. `.ids` en los descartes).
 * 2. **Sólo se prefetchea lo que el servidor puede saber igual que el
 *    navegador.** La organización activa vive en `localStorage`
 *    (`useOrganizationStore`): el servidor no la ve, así que una consulta que
 *    dependa de ella se hidrataría con la organización por defecto y quien
 *    eligió otra recibiría un HTML distinto del de su primer render — un
 *    desajuste de hidratación. Esas consultas se quedan en el cliente.
 * 3. **El prefetch nunca rompe ni bloquea la página.** Cada consulta tiene un
 *    presupuesto de {@link PRESUPUESTO_PREFETCH_MS} ms; `prefetchQuery` no
 *    lanza, y `dehydrate` sólo vuelca las que acabaron bien. Una API lenta o
 *    caída —Render free con spin-down— deja la página exactamente como estaba
 *    antes de este módulo: el hook pide el dato desde el navegador.
 *
 * `force-dynamic` sigue en `(dashboard)/layout.tsx` por privacidad; ahora
 * además el render de servidor hace algo útil.
 *
 * **Coste conocido:** estas peticiones salen de la IP de egreso del servidor de
 * Next, no de la del usuario, y el rate-limit de la API es por IP
 * (`api/middleware.py::_client_key`). Con el tráfico actual —dos consultas por
 * entrada a Resumen o Radar— queda lejísimos del tope, pero si el dashboard
 * crece hay que darle a estas llamadas un bucket propio antes de añadir más.
 */

/** Presupuesto por consulta. Pasado, la consulta se abandona y la pide el cliente. */
export const PRESUPUESTO_PREFETCH_MS = 2_000;

export interface ConsultaServidor {
  /** La misma clave que usa el hook del cliente. */
  queryKey: QueryKey;
  /** Ruta de la API con su query ya resuelta (`/api/v1/...?a=b`). */
  path: string;
  /**
   * Lo que el `queryFn` del hook hace con el cuerpo antes de cachearlo. Por
   * defecto, nada: el cuerpo JSON tal cual (`fetchWithAuth`, `apiGet`).
   */
  transformar?: (cuerpo: unknown) => unknown;
}

/**
 * Origen de la API para llamadas desde el servidor. Los rewrites de
 * `next.config.ts` sólo se aplican a lo que entra desde el navegador, así que
 * aquí se apunta al backend directamente (igual que `lib/publico-api.ts`).
 */
function origenApi(): string {
  // fdi-allow:localhost-url — fallback de desarrollo para fetch SSR; no es dato renderizado.
  return process.env.API_BASE_URL ?? "http://localhost:8080";
}

async function pedir(consulta: ConsultaServidor, cookie: string): Promise<unknown> {
  const res = await fetch(`${origenApi()}${consulta.path}`, {
    // La cookie de sesión es de este origen (el navegador la manda a `/api/*`
    // porque `next.config.ts` lo proxya); reenviarla es lo mismo que hace el
    // rewrite, sólo que desde el servidor.
    headers: { cookie, accept: "application/json" },
    cache: "no-store",
    signal: AbortSignal.timeout(PRESUPUESTO_PREFETCH_MS),
  });
  if (!res.ok) throw new Error(`prefetch ${consulta.path}: ${res.status}`);
  const cuerpo: unknown = await res.json();
  return consulta.transformar ? consulta.transformar(cuerpo) : cuerpo;
}

/**
 * Pide en paralelo las consultas y devuelve el estado deshidratado para
 * `HydrationBoundary`. Sin cookie no pide nada: el proxy de borde ya manda a
 * `/login` a quien no tiene sesión, y una petición anónima sólo devolvería 401.
 */
export async function prefetchEnServidor(
  consultas: readonly ConsultaServidor[],
): Promise<DehydratedState> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const cookie = (await headers()).get("cookie");
  if (cookie) {
    await Promise.all(
      consultas.map((consulta) =>
        queryClient.prefetchQuery({
          queryKey: consulta.queryKey,
          queryFn: () => pedir(consulta, cookie),
        }),
      ),
    );
  }
  return dehydrate(queryClient);
}
