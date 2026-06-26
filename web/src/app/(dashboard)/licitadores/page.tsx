import { redirect } from "next/navigation";

/**
 * `licitadores` se consolidó en `competidores` (RFC ux-licitadores): ambas
 * renderizaban el mismo endpoint `/api/v1/analytics/competitors` con UX
 * divergente. Esta ruta redirige para no romper deep-links guardados; el análisis
 * competitivo vive ahora solo en `/competidores`.
 */
export default function LicitadoresPage() {
  redirect("/competidores");
}
