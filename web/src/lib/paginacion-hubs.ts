/**
 * Paginación de los hubs públicos servida desde la caché ISR, sin tocar su URL.
 *
 * Los tres hubs —por comunidad, por órgano y por código CPV— paginan con `?p=N`,
 * y esa es la URL pública: la enlaza `(publico)/_components/paginacion.tsx`, la
 * declaran el canonical y los `rel="prev"`/`rel="next"`, y es la que tiene
 * indexada Google. Lo que una página no puede hacer es **leerla**: en Next 16,
 * leer `searchParams` obliga a renderizar en cada petición. Eso, sumado a que
 * ninguna declaraba `generateStaticParams`, dejaba a los hubs fuera de la caché
 * pese a su `revalidate = 3600`: cada visita y cada rastreo pagaban un render de
 * servidor y una llamada a la API.
 *
 * Ahora ninguna página lee la query. `src/proxy.ts` traduce `?p=N` (N ≥ 2) a un
 * segmento de ruta con `NextResponse.rewrite`, la página recibe el número por
 * `params` y cada página del hub tiene su propia entrada en la caché. La página
 * 1 se sirve sin rewrite, en su URL de siempre.
 *
 * ## Un prefijo propio, y no un segmento dentro del hub
 *
 * `/licitaciones/{ccaa}/pagina/{n}` tendría la forma de una ficha
 * (`/licitaciones/{ccaa}/{slug}/{ref}`), y el segmento estático taparía la de
 * cualquier anuncio cuyo título se slugificara como «pagina». Bajo su propio
 * prefijo no choca con ninguna ruta, robots.txt lo bloquea sin tocarlo (la
 * política es allowlist) y el proxy lo cierra con una sola comprobación. El
 * árbol interno replica el público —prefijo, ruta del hub y número de página—,
 * así que la carpeta de cada página interna dice qué URL pública sirve.
 *
 * ## El acceso directo es un 404
 *
 * Servir el prefijo tal cual publicaría cada página del hub bajo dos URLs.
 * Marcar la página interna `noindex` no lo arregla: la página no sabe por qué
 * URL la pidieron, así que el `noindex` saldría también en `?p=N`. El proxy sí
 * lo sabe, porque solo ve las peticiones que entran de fuera —su propio rewrite
 * no vuelve a pasar por él—: lo que le llega con este prefijo es por definición
 * un acceso directo, y contesta 404 antes de renderizar nada. El canonical, que
 * apunta siempre a la forma `?p=N`, queda como segunda línea.
 */

/** Prefijo del árbol interno, `app/(publico)/hub-paginado/`. */
export const PREFIJO_PAGINACION_INTERNA = "/hub-paginado";

/**
 * Rutas públicas de los hubs que paginan con `?p=`.
 *
 * `organo` queda fuera del de comunidad porque es una ruta estática hermana de
 * `[ccaa]` —el índice de órganos— que no pagina: sin la exclusión,
 * `/licitaciones/organo?p=2` acabaría en el hub de una comunidad llamada
 * «organo», que es un 404, en vez de en el índice que se sirve hoy.
 * `src/__tests__/rutas-publicas.test.ts` recorre el disco y falla si aparece otra
 * hermana estática que esta lista reescribiría a una página interna inexistente.
 */
const HUBS_PAGINADOS: readonly RegExp[] = [
  /^\/licitaciones\/(?!organo$)[^/]+$/,
  /^\/licitaciones\/organo\/[^/]+$/,
  /^\/cpv\/[^/]+$/,
];

/** La ruta decodificada, o la original si trae una secuencia `%` inválida. */
function decodificar(pathname: string): string {
  try {
    return decodeURIComponent(pathname);
  } catch {
    return pathname;
  }
}

/**
 * Página pedida en `?p=`, con la regla exacta que tenían los hubs cuando leían
 * la query: lo que no sea un entero mayor que 1 es la página 1.
 *
 * Recibe todos los valores de `p` y no solo el primero. Con la clave repetida
 * (`?p=3&p=4`) Next entregaba un array, `Number()` de un array de dos da `NaN` y
 * la página caía en la 1; quedarse con el primero habría cambiado ese caso.
 */
export function paginaDeQuery(valores: readonly string[]): number {
  const n = Number(valores.length === 1 ? valores[0] : undefined);
  return Number.isInteger(n) && n > 1 ? n : 1;
}

/**
 * Página que trae el segmento interno, o `null` si no es una que el proxy pueda
 * haber escrito: dígitos sin cero inicial, mayor que 1 y representable sin
 * pérdida. Las páginas internas convierten el `null` en un 404.
 *
 * Lo que se descarta no es ninguna página que exista. `?p=1e21` pasa la regla
 * de la query —es un entero— pero se escribe «1e+21», y por encima de
 * `Number.MAX_SAFE_INTEGER` el número ya no es el que se pidió. Antes esos
 * casos llegaban a la API con un `offset` absurdo; ahora son un 404 sin
 * preguntar.
 */
export function paginaDeSegmento(segmento: string): number | null {
  if (!/^[1-9]\d*$/.test(segmento)) return null;
  const n = Number(segmento);
  return Number.isSafeInteger(n) && n > 1 ? n : null;
}

/**
 * URL pública de una página de un hub: la 1 sin query —la misma lista bajo dos
 * URLs sería contenido duplicado— y el resto con `?p=`. Es la forma que declara
 * el canonical y la que `destinoPaginaInterna` sabe leer.
 */
export function rutaPublicaDePagina(base: string, pagina: number): string {
  return pagina > 1 ? `${base}?p=${pagina}` : base;
}

/**
 * Ruta interna a la que el proxy reescribe la petición, o `null` si se sirve tal
 * cual: no es un hub, o pide la página 1 (sin `p`, con `?p=1` o con un `p` que
 * no vale, como hasta ahora).
 *
 * Se decide sobre la ruta decodificada, que es contra la que Next casa también
 * las rutas estáticas (`/licitaciones/%6Frgano` es el índice de órganos, no un
 * hub), y el destino se escribe con la ruta tal como llegó: así Next decodifica
 * el parámetro del hub igual que en la página 1. La query no viaja: la página
 * interna no la lee, y fuera de la clave de caché no hay nada que duplicar.
 */
export function destinoPaginaInterna(pathname: string, query: URLSearchParams): string | null {
  const ruta = decodificar(pathname);
  if (!HUBS_PAGINADOS.some((hub) => hub.test(ruta))) return null;
  const pagina = paginaDeQuery(query.getAll("p"));
  return pagina > 1 ? `${PREFIJO_PAGINACION_INTERNA}${pathname}/${pagina}` : null;
}

/**
 * ¿Apunta la petición al árbol interno?
 *
 * Se mira la ruta decodificada y en minúsculas, no solo la cruda: Next casa las
 * rutas también contra la versión decodificada (`resolve-routes` y
 * `filesystem` en `next/dist/server/lib/router-utils/`), de modo que
 * `/hub%2Dpaginado/…` llegaría a una página interna aunque su forma cruda no
 * empiece por el prefijo. Esta comprobación es una lista de denegación, y una
 * lista de denegación solo vale si cubre todas las grafías que el router acepta.
 */
export function esRutaPaginacionInterna(pathname: string): boolean {
  const ruta = decodificar(pathname).toLowerCase();
  return ruta === PREFIJO_PAGINACION_INTERNA || ruta.startsWith(`${PREFIJO_PAGINACION_INTERNA}/`);
}
