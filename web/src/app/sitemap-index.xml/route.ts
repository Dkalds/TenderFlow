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

// Una hora, igual que el dato que enumera.
//
// La versión anterior de este comentario justificaba el plazo diciendo que
// «`generateSitemaps` se evalúa en el build», y eso es falso: el handler que
// Next genera para las rutas de sitemap particionado **vuelve a llamar a
// `generateSitemaps()` en cada petición** y responde 404 si el `id` pedido no
// está en la lista que devuelve (verificado en
// `node_modules/next/dist/build/webpack/loaders/next-metadata-route-loader.js`,
// función `getDynamicSitemapRouteCode`, no deducido de la documentación).
//
// La consecuencia es la buena, y conviene dejarla escrita porque no es obvia:
// el índice y los ficheros derivan del MISMO recuento vivo, así que cuando el
// corpus cruza un múltiplo de `SITEMAP_POR_FICHERO` el tramo nuevo aparece en
// los dos a la vez. `generateStaticParams` solo decide qué tramos se
// prerenderizan; uno posterior se genera bajo demanda y se sirve igual.
//
// Lo que sí hay que conservar es que las dos mitades cuenten igual: si este
// índice y `app/sitemap.ts` usaran fuentes distintas del total, volvería el
// error de cobertura que esta separación evita.
export const revalidate = 3600;

export async function GET(): Promise<Response> {
  // Sin `try`/`catch` a propósito. Si la API no contesta, `contarPublicables`
  // lanza y esta ruta falla; con ISR eso conserva el índice ya generado, y en
  // frío devuelve un 500 que Googlebot reintenta. Capturar para servir un índice
  // de reserva sería lo peor de los dos mundos: un índice con un solo fichero
  // —"las otras 580.000 URLs han desaparecido"— **horneado en la caché** de la
  // ruta durante la hora siguiente, porque este handler es estático.
  const total = await contarPublicables();
  const tramos = Math.ceil(total / SITEMAP_POR_FICHERO);

  // +1 por el fichero 0, que lleva las páginas estáticas y existe siempre.
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
