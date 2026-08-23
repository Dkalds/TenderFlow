import type { components } from "@/generated/api";

/**
 * Acceso a `/api/v1/publico` desde Server Components.
 *
 * No usa el cliente tipado de `api-client.ts` a propósito. Aquél está pensado
 * para el navegador: envía cookies (`credentials: "include"`) y redirige a
 * `/login` ante un 401. Aquí no hay ni cookie ni navegador — y sobre todo, una
 * redirección a login sería exactamente lo contrario de lo que debe pasar en
 * una página pública.
 *
 * Los tipos sí salen del esquema generado, así que un cambio en el contrato de
 * la API rompe el build en vez de romper la página en producción.
 */

export type LicitacionPublica = components["schemas"]["LicitacionPublica"];
export type EntradaSitemap = components["schemas"]["EntradaSitemap"];
export type Hubs = components["schemas"]["Hubs"];

/**
 * Origen de la API para llamadas desde el servidor.
 *
 * `next.config.ts` reescribe `/api/*` hacia el backend, pero esos rewrites los
 * aplica el proxy a las peticiones que **entran** desde el navegador: un
 * `fetch` que hace el propio servidor de Next no pasa por ahí. Hay que apuntar
 * al backend directamente.
 */
function origenApi(): string {
  // fdi-allow:localhost-url — fallback de desarrollo para fetch SSR; no es dato renderizado.
  return process.env.API_BASE_URL ?? "http://localhost:8080";
}

/**
 * Cada cuánto se revalida el dato público.
 *
 * Una hora es deliberadamente conservador frente a la cadencia real de ingesta
 * (cada cuatro horas): el coste de servir un anuncio una hora desactualizado es
 * nulo —la página enlaza al original y muestra su fecha de actualización— y a
 * cambio absorbe las ráfagas de rastreo sin tocar Postgres.
 */
const REVALIDAR_SEGUNDOS = 3600;

/**
 * URLs por fichero de sitemap.
 *
 * Vive aquí y no en `app/sitemap.ts` porque el índice (`app/sitemap-index.xml`)
 * tiene que calcular exactamente los mismos tramos: si las dos cifras
 * divergieran, el índice anunciaría ficheros que no existen o se dejaría fuera
 * los últimos, y en los dos casos Search Console lo reporta como error de
 * cobertura sin decir por qué.
 *
 * 10.000 y no el máximo de 50.000 que admite Google: el límite es el techo, no
 * el objetivo. Un tramo más corto evita pedirle al backend medio corpus de una
 * vez y hace que un fallo pierda una porción proporcional, no el fichero entero.
 */
export const SITEMAP_POR_FICHERO = 10_000;

async function pedir<T>(ruta: string): Promise<T | null> {
  let respuesta: Response;
  try {
    respuesta = await fetch(`${origenApi()}/api/v1/publico${ruta}`, {
      next: { revalidate: REVALIDAR_SEGUNDOS },
      headers: { Accept: "application/json" },
    });
  } catch {
    // La API caída no puede tumbar la página: el llamante decide si eso es un
    // 404, una lista vacía o un sitemap más corto. Propagar aquí convertiría
    // una incidencia de backend en un error 500 indexable.
    return null;
  }

  if (!respuesta.ok) return null;
  return (await respuesta.json()) as T;
}

/** Anuncio público de un expediente. `null` si no existe o no es publicable. */
export function obtenerLicitacion(ref: string): Promise<LicitacionPublica | null> {
  return pedir<LicitacionPublica>(`/licitaciones/${encodeURIComponent(ref)}`);
}

/**
 * Listado público, filtrable por slug de comunidad autónoma o prefijo CPV.
 *
 * Devuelve también el `total` real con los filtros aplicados, no el tamaño de
 * la página: es lo que necesita la paginación del hub para saber si hay página
 * siguiente.
 */
export async function listarLicitaciones(params: {
  ccaa?: string;
  cpv?: string;
  limit?: number;
  offset?: number;
}): Promise<{ items: LicitacionPublica[]; total: number }> {
  const query = new URLSearchParams();
  if (params.ccaa) query.set("ccaa", params.ccaa);
  if (params.cpv) query.set("cpv", params.cpv);
  query.set("limit", String(params.limit ?? 50));
  query.set("offset", String(params.offset ?? 0));

  const pagina = await pedir<{ items: LicitacionPublica[]; total: number }>(
    `/licitaciones?${query}`,
  );
  return { items: pagina?.items ?? [], total: pagina?.total ?? 0 };
}

/**
 * Comunidades y códigos CPV con volumen suficiente para tener índice.
 *
 * Las listas ya vienen filtradas por umbral del backend. Alimentan las páginas
 * `/licitaciones` y `/cpv`, que son las que reparten autoridad interna hacia
 * los hubs — sin ellas, los hubs solo se descubren por sitemap y ningún enlace
 * les transmite relevancia.
 */
export async function obtenerHubs(): Promise<Hubs> {
  return (await pedir<Hubs>("/hubs")) ?? { ccaa: [], cpv: [] };
}

/** Cuántas URLs publicables hay. Dimensiona la partición del sitemap. */
export async function contarPublicables(): Promise<number> {
  const resumen = await pedir<{ total: number }>("/sitemap/resumen");
  return resumen?.total ?? 0;
}

/** Un tramo estable de entradas para un fichero de sitemap. */
export async function entradasSitemap(
  offset: number,
  limit: number,
): Promise<EntradaSitemap[]> {
  return (
    (await pedir<EntradaSitemap[]>(`/sitemap/entradas?offset=${offset}&limit=${limit}`)) ?? []
  );
}
