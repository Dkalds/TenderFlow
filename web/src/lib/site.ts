import { CONTENIDO } from "@/app/(publico)/_content/landing";
import type { Metadata } from "next";

/**
 * Identidad pública del sitio: origen absoluto, nombre y descripción.
 *
 * Vive aparte porque lo consumen tres sitios que tienen que coincidir o el SEO
 * se rompe en silencio: el `metadataBase` de `app/layout.tsx` (del que cuelgan
 * canonical y Open Graph), `app/robots.ts` y el futuro `app/sitemap.ts`. Un
 * origen distinto entre ellos produce canonicals que apuntan a un dominio y
 * sitemaps que anuncian otro, que es de los errores más caros de diagnosticar.
 */

/**
 * Origen del sitio, sin barra final.
 *
 * El orden de resolución importa:
 *
 * 1. `NEXT_PUBLIC_SITE_URL` — la única que sobrevive a un dominio propio. Es la
 *    que hay que definir en el proyecto de Vercel cuando TenderFlow deje de
 *    servirse desde `*.vercel.app`.
 * 2. `VERCEL_PROJECT_PRODUCTION_URL` — Vercel la inyecta sola y apunta al
 *    dominio de **producción** del proyecto, no al de la preview. Eso es
 *    justo lo que queremos: un canonical emitido desde una preview debe
 *    señalar a producción, nunca a la URL efímera del despliegue, o Google
 *    acabaría indexando previews.
 * 3. `http://localhost:3000` — desarrollo.
 *
 * Sin el paso 2 haría falta configurar una variable para que el build de Vercel
 * emitiera metadatos correctos; así funciona por defecto y la variable queda
 * como override para el dominio definitivo.
 */
function resolveSiteUrl(): string {
  const explicito = process.env.NEXT_PUBLIC_SITE_URL;
  if (explicito) return explicito.replace(/\/$/, "");

  const vercel = process.env.VERCEL_PROJECT_PRODUCTION_URL;
  if (vercel) return `https://${vercel}`;

  // fdi-allow:localhost-url — fallback de desarrollo para metadatos; no es dato renderizado.
  return "http://localhost:3000";
}

export const SITE_URL = resolveSiteUrl();

export const SITE_NAME = "TenderFlow";

/**
 * Descripción por defecto. Se reutiliza en `<meta name="description">`, en Open
 * Graph y en la Twitter card para que las tres digan lo mismo; ~150 caracteres,
 * que es lo que Google muestra antes de truncar.
 *
 * Sale del contenido de la landing en vez de tener redacción propia. Eran dos
 * textos distintos para el mismo posicionamiento —uno aquí y otro en
 * `landing.ts`—, los dos se emitían (éste en la raíz, aquél en la portada) y no
 * había nada que los mantuviera alineados: cualquier revisión del copy dejaba
 * el otro atrás sin que fallara nada.
 */
export const SITE_DESCRIPTION = CONTENIDO.metaDescription;

/**
 * Imagen Open Graph, para **esparcir** en el `openGraph` de cualquier página
 * que declare el suyo.
 *
 * Hace falta por cómo fusiona Next los metadatos: los objetos se combinan de
 * forma *superficial*, así que una página que exporta `openGraph` **reemplaza
 * entero** el del layout padre, incluida la imagen que `app/opengraph-image.tsx`
 * inyecta automáticamente. El síntoma es silencioso y caro: la página se
 * comparte en Slack o LinkedIn sin preview, y nada falla en el build.
 *
 * Ocurrió de verdad al montar la landing. Por eso vive aquí y no incrustado en
 * una página: cada ruta pública nueva que declare `openGraph` tiene que
 * esparcir esto.
 *
 * No se declara en el layout raíz a propósito. Las páginas que **no** pisan
 * `openGraph` —`/login`, por ejemplo— ya reciben la imagen por convención de
 * fichero; añadirla también arriba emitiría dos `og:image`.
 *
 * La URL se deja relativa: `metadataBase` la vuelve absoluta, que es como los
 * unfurlers la necesitan.
 */
/**
 * Tipo de tarjeta de Twitter/X, para esparcir igual que `OG_IMAGE_COMPARTIDA`.
 *
 * Misma trampa y por el mismo motivo: una página que declara `twitter` para
 * poner su título reemplaza el objeto entero y se deja por el camino el
 * `card: "summary_large_image"` del layout raíz. El resultado es que el enlace
 * se despliega como tarjeta pequeña cuadrada en vez de con la imagen grande.
 *
 * La imagen no hace falta declararla: Next la deriva de `openGraph.images`.
 */
// El tipo se escribe a mano —y no con `Pick<Metadata["twitter"], "card">`—
// porque `twitter` es una unión discriminada por el propio `card`, así que
// `card` no es una clave común a todos sus miembros y `Pick` no la encuentra.
export const TWITTER_COMPARTIDO: { card: "summary_large_image" } = {
  card: "summary_large_image",
};

export const OG_IMAGE_COMPARTIDA: Pick<NonNullable<Metadata["openGraph"]>, "images"> = {
  images: [
    {
      url: "/opengraph-image",
      width: 1200,
      height: 630,
      alt: `${SITE_NAME} — Radar de licitaciones TI del sector público español`,
    },
  ],
};
