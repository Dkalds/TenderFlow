import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

/**
 * Sitemap.
 *
 * Hoy sólo contiene la portada, porque hoy sólo la portada es indexable: el
 * resto de la aplicación es dashboard privado. Un sitemap que anunciara URLs
 * que devuelven un 307 a `/login` sería peor que no tenerlo — Search Console lo
 * reporta como error de cobertura y desperdicia presupuesto de rastreo.
 *
 * Cuando existan las páginas públicas de datos, esto crece por entidad
 * (licitaciones, órganos, empresas, CPV) y habrá que particionarlo con
 * `generateSitemaps`: el límite son 50.000 URLs por fichero.
 *
 * `lastModified` se congela en el momento del build, y es lo correcto para una
 * página estática: su última modificación real es el último despliegue.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: SITE_URL,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 1,
    },
  ];
}
