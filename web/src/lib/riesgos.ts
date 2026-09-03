/**
 * Etiquetas legibles de los avisos que acompañan a un score.
 *
 * La API devuelve `risk_flags` como identificadores en crudo
 * (`sin_historico_competencia`, `sin_senal_tecnica`) y hasta ahora los cuatro
 * sitios que los pintan los enseñaban tal cual, en snake_case, dentro de un chip
 * de color de aviso. Un identificador de código en la interfaz no informa: se
 * lee como un error del programa, y en la captura de la landing —donde salían
 * dos de ellos junto al expediente destacado— eso era lo primero que veía quien
 * no conoce el producto.
 *
 * Lo que dicen estos avisos es una sola cosa, y conviene que la digan: **esa
 * dimensión no tenía dato, así que se puntuó en el valor neutro**. No es una
 * penalización ni un defecto del expediente; es la trazabilidad de la que
 * presume el producto. Las etiquetas están escritas desde esa idea.
 *
 * Espejo de las banderas que emite `services/analytics/scoring.py` (`flags.append`).
 * Cuando el backend añada una nueva, aquí no habrá entrada y la degradación de
 * abajo la deja legible en vez de dejarla en crudo: no hace falta desplegar las
 * dos cosas a la vez.
 */

const RIESGO_LABELS: Record<string, string> = {
  sin_importe: "Sin importe publicado",
  sin_plazo: "Sin fecha límite",
  sin_historico_competencia: "Sin histórico de competencia",
  sin_prediccion: "Sin predicción de baja",
  sin_senal_tecnica: "Sin señal técnica",
  sin_titulo: "Sin título",
  fuera_de_rango: "Fuera de tu rango de importe",
};

/**
 * Etiqueta legible de un aviso, conocido o no.
 *
 * Un identificador sin traducir se convierte en texto normal
 * (`sin_datos_de_lote` → «Sin datos de lote») en vez de mostrarse con guiones
 * bajos. Es una degradación y no una traducción: si un aviso nuevo aparece a
 * menudo, merece su entrada arriba.
 */
export function riesgoLabel(flag: string): string {
  const conocido = RIESGO_LABELS[flag];
  if (conocido) return conocido;

  const legible = flag.replace(/_/g, " ").trim();
  if (!legible) return flag;
  return legible.charAt(0).toUpperCase() + legible.slice(1);
}
