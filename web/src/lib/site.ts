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
 */
export const SITE_DESCRIPTION =
  "Inteligencia de mercado para licitaciones de tecnología del sector público " +
  "español: seguimiento de concursos, análisis competitivo y alertas.";
