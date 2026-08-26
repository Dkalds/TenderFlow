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
