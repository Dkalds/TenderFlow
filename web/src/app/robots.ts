import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";
import { rutasRastreables } from "@/lib/rutas-publicas";

/**
 * robots.txt.
 *
 * La regla se lee al revés de lo habitual: **se bloquea todo y se abre lo
 * público**, en vez de abrir todo y enumerar lo privado. Es el reflejo honesto
 * del producto —TenderFlow es un dashboard privado con una superficie pública
 * delante, no al revés— y sobre todo es la política que falla en la dirección
 * segura: una ruta de dashboard nueva nace bloqueada sin que nadie se acuerde
 * de añadirla, mientras que la lista inversa dejaría expuesta cada pantalla
 * interna que alguien olvidara enumerar. Hay 36 rutas en `(dashboard)`; la
 * probabilidad de que esa lista se quedara desactualizada era del 100 %.
 *
 * El coste del enfoque es el simétrico y es asumible: una ruta pública nueva
 * que nadie añada aquí simplemente no se rastrea. Se nota en Search Console y
 * no filtra nada.
 *
 * `Allow: /$` es la portada y solo la portada — el `$` ancla el final de la
 * URL, así que no arrastra `/resumen`. Google resuelve los conflictos por
 * especificidad: gana la regla más larga que casa.
 *
 * `/login` queda rastreable a propósito, y es el matiz que hace que esto
 * funcione: una página bloqueada por robots no puede rastrearse, así que Google
 * tampoco puede leer su `noindex` y nunca la sacaría del índice. Se deja entrar
 * para que lea el `noindex` que declara `app/login/layout.tsx`.
 *
 * La lista ya no se escribe aquí: sale de `lib/rutas-publicas.ts`, la misma que
 * decide qué sirve el proxy sin sesión y qué anuncia el sitemap. Cuando eran
 * tres listas independientes, tres páginas publicadas se quedaron fuera de las
 * tres a la vez.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: rutasRastreables(),
      disallow: "/",
    },
    // Al índice y no a `/sitemap.xml`: con `generateSitemaps`, Next sirve
    // `/sitemap/N.xml` pero no crea índice, y `/sitemap.xml` devuelve 404.
    // Anunciar una URL muerta aquí es un error de cobertura en Search Console.
    sitemap: `${SITE_URL}/sitemap-index.xml`,
  };
}
