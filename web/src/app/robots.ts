import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

/**
 * robots.txt.
 *
 * La regla se lee al revés de lo habitual: se bloquea todo y se abre lo poco
 * que es público. Es el reflejo honesto del producto — TenderFlow es un
 * dashboard privado con una landing delante, no un sitio público con una zona
 * privada.
 *
 * `Allow: /$` es la portada y sólo la portada: el `$` ancla el final de la URL,
 * así que no arrastra `/resumen` ni el resto del dashboard. Google resuelve los
 * conflictos por especificidad —gana la regla más larga que casa—, de modo que
 * para `/` gana el `Allow` y para `/resumen` gana el `Disallow`.
 *
 * `/login` queda rastreable a propósito, y es el matiz que hace que esto
 * funcione: una página bloqueada por robots no puede rastrearse, así que Google
 * tampoco puede leer su `noindex` y nunca la sacaría del índice. Se deja entrar
 * para que lea el `noindex` que declara `app/login/layout.tsx`.
 *
 * Con la superficie pública de datos esta lista se invierte: pasará a
 * `Allow: /` con un `Disallow` explícito por cada ruta del dashboard.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: ["/$", "/login"],
      disallow: "/",
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
