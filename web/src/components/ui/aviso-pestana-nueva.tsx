/**
 * Aviso para lector de pantalla en todo enlace con `target="_blank"`: el
 * `ExternalLink` que lo marca a la vista lleva `aria-hidden`.
 */
export const AVISO_PESTANA_NUEVA = " (se abre en otra pestaña)";

export function AvisoPestanaNueva() {
  return <span className="sr-only">{AVISO_PESTANA_NUEVA}</span>;
}
