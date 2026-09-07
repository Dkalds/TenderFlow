export interface TimelineItem {
  id_externo: string;
  titulo: string;
  importe: number | null;
  fecha_publicacion: string;
  estado: string;
  organo_contratacion: string | null;
  tipo_contrato: string | null;
  ccaa: string | null;
}

export const ITEMS_PER_PAGE = 10;

/**
 * Tope de filas de `GET /analytics/resumen/timeline` (`_TIMELINE_LIMIT` en
 * `services/analytics/resumen.py`). El frontend lo necesita para **declarar**
 * el recorte: la tabla decía «1–10 de 1.000» y ese 1.000 se leía como el total
 * del ámbito, cuando es el tope del endpoint. Si el backend lo cambia, aquí se
 * queda corto el aviso, nunca el dato — por eso se compara con `>=`.
 */
export const TIMELINE_MAX = 1000;

/**
 * ¿Publicada después de la última visita?
 *
 * Es el mismo predicado que cuenta el backend —`fecha_publicacion >= desde` en
 * `resumen_novedades`—, aplicado al corte que ese endpoint publica en `desde`.
 * Sin corte no se marca nada: marcar sólo las filas de la muestra dejaría al
 * resto de novedades con la misma pinta que lo viejo, y una marca ausente se
 * lee como «esta no es nueva», no como «no lo sé».
 */
export function esNueva(
  fechaPublicacion: string | null | undefined,
  desde: string | null | undefined,
): boolean {
  if (!fechaPublicacion || !desde) return false;
  const publicada = Date.parse(fechaPublicacion);
  const corte = Date.parse(desde);
  if (Number.isNaN(publicada) || Number.isNaN(corte)) return false;
  return publicada >= corte;
}
