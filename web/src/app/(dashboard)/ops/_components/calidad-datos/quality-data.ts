/**
 * Forma del payload de `/api/v1/analytics/quality` y las dos derivaciones que
 * la pantalla necesita.
 *
 * Ambas son puras y ninguna inventa dato: `completitudSeries` **descarta** las
 * columnas que el backend no manda en vez de rellenarlas con cero, y
 * `freshnessInfo` se abstiene sin horas medidas. Es la misma regla de ADR-014
 * que rige el resto de la pantalla, sólo que aquí escrita una vez.
 */

export interface ColumnCompleteness {
  columna: string;
  pct: number;
}

export interface QualityData {
  total_records?: number;
  pct_cpv?: number;
  pct_importe?: number;
  pct_fecha?: number;
  pct_titulo?: number;
  completitud_columnas?: ColumnCompleteness[];
  // `null` = NO MEDIDO (ni `nif` ni `modulo_sap` son columnas de
  // `licitaciones`), y la tarjeta se abstiene. El backend devolvía el literal
  // 0.0, que la guarda `!= null` daba por bueno: la pantalla que existe para
  // acreditar la calidad del dato afirmaba una cobertura del 0,0 % que nadie
  // había medido.
  cobertura_nif?: number | null;
  cobertura_modulo_sap?: number | null;
  dlq_count?: number;
  pct_fecha_iso?: number;
  fechas_no_iso?: number;
  last_scrape_hours_ago?: number;
  last_scrape_at?: string;
  [key: string]: unknown;
}

export interface Frescura {
  label: string;
  color: string;
  badge: "default" | "secondary" | "destructive";
}

/** Umbrales de frescura del scraping, en horas desde la última ingesta. */
export const FRESCURA_OK_H = 6;
export const FRESCURA_LIMITE_H = 24;

export function freshnessInfo(hours: number | null | undefined): Frescura {
  if (hours == null) return { label: "N/A", color: "", badge: "secondary" };
  if (hours < FRESCURA_OK_H)
    return { label: "Actualizado", color: "text-green-700", badge: "default" };
  if (hours <= FRESCURA_LIMITE_H)
    return { label: "Pendiente", color: "text-yellow-700", badge: "secondary" };
  return { label: "Obsoleto", color: "text-red-700", badge: "destructive" };
}

/**
 * Serie del gráfico de completitud: `completitud_columnas` si viene, y si no
 * los `pct_*` sueltos.
 *
 * Los `pct_*` que el backend no manda se **filtran**, no se rellenan con 0: una
 * barra a 0,0 % en la pantalla de Calidad de Datos afirma que ninguna fila
 * tiene título, que es la misma cobertura inventada que #228 quitó de las dos
 * tarjetas de cobertura. Sin dato, la columna no entra en el gráfico.
 */
export function completitudSeries(data: QualityData | undefined): ColumnCompleteness[] {
  if (data?.completitud_columnas && data.completitud_columnas.length > 0) {
    return data.completitud_columnas;
  }
  const sueltos: { columna: string; pct?: number | null }[] = [
    { columna: "Título", pct: data?.pct_titulo },
    { columna: "CPV", pct: data?.pct_cpv },
    { columna: "Importe", pct: data?.pct_importe },
    { columna: "Fecha", pct: data?.pct_fecha },
  ];
  return sueltos
    .filter((c): c is ColumnCompleteness => c.pct != null)
    .map((c) => ({ columna: c.columna, pct: c.pct }));
}
