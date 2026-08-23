import type { MetadataRoute } from "next";
import { SITE_DESCRIPTION, SITE_NAME } from "@/lib/site";

/**
 * Web App Manifest.
 *
 * Los colores replican los `themeColor` declarados en el `viewport` de
 * `app/layout.tsx` (`#090E11` oscuro / `#F7F5F3` claro): el manifest no puede
 * leerlos de las variables CSS, así que si cambia la paleta hay que tocar los
 * dos sitios.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: SITE_NAME,
    short_name: SITE_NAME,
    description: SITE_DESCRIPTION,
    start_url: "/",
    display: "standalone",
    background_color: "#090E11",
    theme_color: "#090E11",
    lang: "es-ES",
    icons: [
      { src: "/favicon.svg", type: "image/svg+xml", sizes: "any" },
      { src: "/favicon.ico", type: "image/x-icon", sizes: "48x48" },
    ],
  };
}
