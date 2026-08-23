import { contarPublicables, SITEMAP_POR_FICHERO } from "@/lib/publico-api";
import { SITE_URL } from "@/lib/site";

/**
 * Índice de sitemaps.
 *
 * Existe porque `generateSitemaps` de Next publica los ficheros en
 * `/sitemap/0.xml`, `/sitemap/1.xml`… **pero no genera el índice que los
 * enumera**: `/sitemap.xml` devuelve 404. Comprobado en ejecución contra el
 * build de producción, no deducido de la documentación.
 *
 * Sin índice habría que declarar cada tramo en `robots.txt` uno a uno, cosa
 * imposible cuando el número de tramos depende del volumen de la base. Con él,
 * `robots.txt` apunta a una sola URL estable y Google descubre el resto.
 *
 * El cálculo de tramos replica el de `app/sitemap.ts` a partir de la misma
 * constante compartida, que es lo que garantiza que el índice no anuncie
 * ficheros inexistentes ni se deje los últimos fuera.
 */

// Una hora, igual que el dato que enumera. `generateSitemaps` se evalúa en el
// build, así que un índice más fresco que sus ficheros no aportaría nada.
export const revalidate = 3600;

export async function GET(): Promise<Response> {
  const total = await contarPublicables();
  const tramos = Math.ceil(total / SITEMAP_POR_FICHERO);

  // +1 por el fichero 0, que lleva las páginas estáticas y existe siempre —
  // también cuando la API no contesta y `total` es 0.
  const ficheros = Array.from(
    { length: tramos + 1 },
    (_, indice) => `${SITE_URL}/sitemap/${indice}.xml`,
  );

  const xml = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...ficheros.map((url) => `<sitemap><loc>${url}</loc></sitemap>`),
    "</sitemapindex>",
  ].join("\n");

  return new Response(xml, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
