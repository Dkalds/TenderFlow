/**
 * Códigos de estado PLACSP y su etiqueta legible.
 *
 * Espejo de `ESTADO_LABELS` en `services/classification.py`. La API devuelve el
 * **código crudo** de `licitaciones.estado` (`PUB`, `EV`, `ADJ`…) y ninguna
 * respuesta lo traduce: `estado_label()` sólo se usa dentro del backend. El
 * frontend, en cambio, tenía dos tablas indexadas por la etiqueta castellana
 * —`ESTADO_CHART_COLOR` en `lib/chart-colors.ts` y `ESTADO_STYLES` en
 * `components/ui/status-badge.tsx`—, así que **todas sus búsquedas fallaban en
 * silencio** y caían al valor por defecto:
 *
 * - el scatter del Resumen pintaba sus mil puntos del mismo color bajo el
 *   rótulo «color por estado»;
 * - la tabla enseñaba `PUB` con el badge neutro, en vez de «Publicada» en azul.
 *
 * Normalizar aquí —y no añadir una segunda entrada por código a cada tabla—
 * deja una sola fuente que traducir el día que la fuente publique un código
 * nuevo. La función es idempotente: acepta el código o la etiqueta ya resuelta,
 * porque los tests y los datos de ejemplo del repo usan la segunda.
 */

export const ESTADO_LABELS: Record<string, string> = {
  PUB: "Publicada",
  EV: "Evaluación",
  RES: "Resuelta",
  ADJ: "Adjudicada",
  ANUL: "Anulada",
  PRE: "Anuncio previo",
  CREA: "Creada",
  // Los dos códigos propios de la PSCP catalana. Nombrados por lo que son y no
  // por su efecto ("Cerrada"): son 1,7 M de contratos menores publicados en
  // bloque frente a 58.528 anuncios de adjudicación reales, y fundirlos con ADJ
  // destrozaría cualquier lectura competitiva.
  AGREG: "Publicación agregada",
  EJEC: "En ejecución",
  // Cajón del embudo por estado: lo que el backend no pudo clasificar en
  // ninguno de los códigos de arriba (filas sin estado, o con el texto crudo que
  // el conector escribió antes del arreglo de 2026-08-27 y que
  // `scripts/repair_estados_pscp.py` todavía no ha limpiado). Existe para que
  // los tramos sumen el total en vez de dejar filas fuera sin decirlo.
  OTROS: "Otros / sin clasificar",
};

/**
 * Etiqueta legible de un estado. Un código desconocido se devuelve tal cual:
 * enseñar el código crudo es peor que enseñar la etiqueta, pero mucho mejor que
 * esconder la fila o inventarle un estado que la fuente no dio.
 */
export function estadoLabel(value: string | null | undefined): string {
  if (!value) return "";
  const trimmed = value.trim();
  return ESTADO_LABELS[trimmed] ?? trimmed;
}
