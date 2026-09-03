import type { MetadataRoute } from "next";
import {
  contarPublicables,
  entradasSitemap,
  obtenerHubs,
  SITEMAP_POR_FICHERO,
} from "@/lib/publico-api";
import { SITE_URL } from "@/lib/site";
import { paginasDeSitemap } from "@/lib/rutas-publicas";
import { rutaHubCcaa, rutaHubCpv, rutaLicitacion } from "@/lib/slug";

/**
 * Sitemap particionado.
 *
 * El límite de Google son 50.000 URLs por fichero, y el corpus de licitaciones
 * lo supera con holgura, así que `generateSitemaps` produce
 * `/sitemap/0.xml`, `/sitemap/1.xml`…
 *
 * Lo que Next **no** produce es el índice que los enumera: `/sitemap.xml`
 * devuelve 404 y por eso existe `app/sitemap-index.xml/route.ts`. Este
 * comentario decía lo contrario y contradecía a sus dos vecinos.
 *
 * El fichero `0` es siempre el de las páginas estáticas, aparte de los tramos
 * de licitaciones: así la portada y los índices no comparten destino con el
 * volumen del corpus.
 *
 * El tamaño de tramo es 10.000 y no 50.000 a propósito. El límite de Google es
 * el techo, no el objetivo: un fichero de 50.000 URLs obliga al backend a
 * paginar medio corpus en una sola petición, y si falla se pierde el tramo
 * entero. Con tramos más cortos el fallo es proporcional.
 *
 * ## Un sitemap corto no es medio sitemap: es una retirada
 *
 * Este módulo prometía que "si el backend está caído, el sitemap de
 * licitaciones sale vacío pero el del sitio sigue siendo correcto". La promesa
 * era peor que el problema que evitaba. Un sitemap que encoge —de 59 ficheros a
 * 1, o de 10.000 URLs a ninguna— le está diciendo a Google que esas URLs han
 * dejado de existir, y desandar eso cuesta semanas de rastreo. No hay ninguna
 * versión truncada que sea mejor que no publicar nada.
 *
 * Por eso ya no hay reservas aquí: `lib/publico-api.ts` lanza cuando no se pudo
 * preguntar, la generación del fichero falla y Next se queda con la copia
 * anterior (o devuelve un 500, que Googlebot reintenta sin sacar conclusiones).
 * Lo único que sigue degradando en silencio es el build deliberadamente sin
 * `API_BASE_URL` del job `frontend` de CI, donde no hay backend que preguntar
 * ni copia previa que proteger.
 */

/**
 * Fichero 0: la portada, los índices y los hubs.
 *
 * Los hubs se consultan al vuelo en vez de escribirse a mano porque su lista
 * depende del dato: solo tienen página las comunidades y los códigos CPV que
 * superan el umbral de volumen del backend. Una lista fija acabaría anunciando
 * hubs que devuelven 404 en cuanto un CPV bajara de umbral.
 *
 * Si la API no contesta, `obtenerHubs` lanza y este fichero no se regenera. Se
 * consideró publicar solo las cuatro páginas fijas, y es peor: un fichero 0 que
 * pasa de 4+N a 4 URLs retira del índice todos los hubs de golpe, que son
 * justamente las páginas que reparten autoridad hacia las fichas.
 */
async function estaticas(): Promise<MetadataRoute.Sitemap> {
  const { ccaa, cpv } = await obtenerHubs();

  return [
    // Las páginas fijas salen de `lib/rutas-publicas.ts`, que es también la
    // lista que abre el proxy y la que permite robots.txt. Escritas aquí a
    // mano, las tres páginas de evidencia llevaban desde su despliegue sin
    // anunciarse.
    ...paginasDeSitemap().map((pagina) => ({
      url: pagina.ruta === "/" ? SITE_URL : `${SITE_URL}${pagina.ruta}`,
      changeFrequency: pagina.frecuencia,
      priority: pagina.prioridad,
    })),
    ...ccaa.map((hub) => ({
      url: `${SITE_URL}${rutaHubCcaa(hub.slug)}`,
      changeFrequency: "daily" as const,
      priority: 0.8,
    })),
    ...cpv.map((hub) => ({
      url: `${SITE_URL}${rutaHubCpv(hub.codigo)}`,
      changeFrequency: "daily" as const,
      priority: 0.7,
    })),
  ];
}

export async function generateSitemaps(): Promise<{ id: number }[]> {
  // Sin este número no se puede particionar nada, y un `0` de reserva anunciaría
  // un único fichero. `contarPublicables` lanza antes que devolverlo inventado.
  const total = await contarPublicables();
  const tramos = Math.ceil(total / SITEMAP_POR_FICHERO);
  // Siempre al menos el fichero de estáticas, aunque no haya ni una licitación
  // publicable.
  return Array.from({ length: tramos + 1 }, (_, indice) => ({ id: indice }));
}

export default async function sitemap({
  id,
}: {
  // En Next 16 el `id` llega como promesa y hay que esperarlo; en versiones
  // anteriores era un número. Confirmado en
  // `node_modules/next/dist/docs/01-app/03-api-reference/04-functions/generate-sitemaps.md`.
  id: Promise<string>;
}): Promise<MetadataRoute.Sitemap> {
  const indice = Number(await id);

  if (indice === 0) return estaticas();

  // Un tramo que no se pudo leer no se publica a medias: `entradasSitemap`
  // lanza y Next conserva el fichero anterior en vez de emitir uno truncado.
  const entradas = await entradasSitemap((indice - 1) * SITEMAP_POR_FICHERO, SITEMAP_POR_FICHERO);

  return entradas.map((entrada) => ({
    url: `${SITE_URL}${rutaLicitacion({
      ccaa: entrada.ccaa,
      titulo: entrada.titulo,
      ref: entrada.ref,
    })}`,
    lastModified: entrada.actualizado ?? undefined,
    changeFrequency: "weekly" as const,
    priority: 0.6,
  }));
}
