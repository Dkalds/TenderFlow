import type { MetadataRoute } from "next";
import { MARCA_HEX } from "@/lib/marca";
import { SITE_DESCRIPTION, SITE_NAME } from "@/lib/site";

/**
 * Web App Manifest.
 *
 * El color es la tinta de la marca (`lib/marca.ts`), el mismo `#090E11` del
 * `themeColor` oscuro que declara el `viewport` de `app/layout.tsx`: el
 * manifest no puede leer variables CSS, y la marca tiene un solo sitio.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: SITE_NAME,
    short_name: SITE_NAME,
    description: SITE_DESCRIPTION,
    start_url: "/",
    display: "standalone",
    background_color: MARCA_HEX.tinta,
    theme_color: MARCA_HEX.tinta,
    lang: "es-ES",
    icons: [
      { src: "/favicon.svg", type: "image/svg+xml", sizes: "any" },
      { src: "/favicon.ico", type: "image/x-icon", sizes: "48x48" },
    ],
  };
}
