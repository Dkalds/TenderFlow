import type { MetadataRoute } from "next";
import {
  contarPublicables,
  entradasSitemap,
  obtenerHubs,
  SITEMAP_POR_FICHERO,
} from "@/lib/publico-api";
import { SITE_URL } from "@/lib/site";
import { rutaHubCcaa, rutaHubCpv, rutaLicitacion } from "@/lib/slug";

/**
 * Sitemap particionado.
 *
 * El límite de Google son 50.000 URLs por fichero, y el corpus de licitaciones
 * lo supera con holgura, así que `generateSitemaps` produce
 * `/sitemap/0.xml`, `/sitemap/1.xml`… y Next sirve el índice en `/sitemap.xml`.
 *
 * El fichero `0` es siempre el de las páginas estáticas. Va aparte de los
 * tramos de licitaciones para que la portada y los hubs no dependan de que la
 * API responda: si el backend está caído, el sitemap de licitaciones sale
 * vacío pero el del sitio sigue siendo correcto.
 *
 * El tamaño de tramo es 10.000 y no 50.000 a propósito. El límite de Google es
 * el techo, no el objetivo: un fichero de 50.000 URLs obliga al backend a
 * paginar medio corpus en una sola petición, y si falla se pierde el tramo
 * entero. Con tramos más cortos el fallo es proporcional.
 */

/**
 * Fichero 0: la portada, los índices y los hubs.
 *
 * Los hubs se consultan al vuelo en vez de escribirse a mano porque su lista
 * depende del dato: solo tienen página las comunidades y los códigos CPV que
 * superan el umbral de volumen del backend. Una lista fija acabaría anunciando
 * hubs que devuelven 404 en cuanto un CPV bajara de umbral.
 *
 * Si la API no contesta, `obtenerHubs` devuelve listas vacías y este fichero se
 * queda con las páginas fijas: un sitemap más corto, nunca uno roto.
 */
async function estaticas(): Promise<MetadataRoute.Sitemap> {
  const { ccaa, cpv } = await obtenerHubs();

  return [
    { url: SITE_URL, changeFrequency: "daily", priority: 1 },
    { url: `${SITE_URL}/licitaciones`, changeFrequency: "daily", priority: 0.9 },
    { url: `${SITE_URL}/cpv`, changeFrequency: "daily", priority: 0.8 },
    { url: `${SITE_URL}/aviso-legal`, changeFrequency: "yearly", priority: 0.1 },
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
  const total = await contarPublicables();
  const tramos = Math.ceil(total / SITEMAP_POR_FICHERO);
  // Siempre al menos el fichero de estáticas, aunque no haya ni una licitación
  // publicable (o la API no conteste).
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
