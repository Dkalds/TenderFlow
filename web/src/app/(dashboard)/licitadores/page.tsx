import { redirect } from "next/navigation";

/**
 * `licitadores` se consolidó en `competidores` (RFC ux-licitadores) y esa ruta
 * vive hoy como vista del espacio Competencia. Redirige directo al destino
 * final (sin doble salto por `/competidores`) para no romper deep-links
 * guardados; el análisis competitivo vive en `/competencia?vista=competidores`.
 */
export default function LicitadoresPage() {
  redirect("/competencia?vista=competidores");
}
