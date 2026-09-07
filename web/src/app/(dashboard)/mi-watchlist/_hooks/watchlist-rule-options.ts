/**
 * Catálogos de los selectores del formulario de reglas.
 *
 * Son copy y listas fijas, no dato derivado: lo que el usuario lee al elegir
 * frecuencia, banda, procedimiento o tipo de contrato. Viven aparte de
 * `use-watchlist-rules.ts` porque los consumen las piezas de `_components/`,
 * que no traducen nada del contrato y no tienen por qué importar el módulo que
 * sí lo hace.
 */

import type { Frequency } from "./watchlist-rule-types";

export const CCAA_FALLBACK = [
  "__all__",
  "Andalucia",
  "Aragon",
  "Asturias",
  "Baleares",
  "Canarias",
  "Cantabria",
  "Castilla y Leon",
  "Castilla-La Mancha",
  "Cataluna",
  "Ceuta",
  "Comunidad Valenciana",
  "Extremadura",
  "Galicia",
  "La Rioja",
  "Madrid",
  "Melilla",
  "Murcia",
  "Navarra",
  "Pais Vasco",
];

/**
 * Etiquetas del selector de frecuencia.
 *
 * `immediate` NO es inmediata y llamarla así prometía una actualidad que la
 * ingesta no da: el job de alertas entrega en el siguiente run de digests y ese
 * cron corre cada 4 horas (`scheduler/watchlist_rules_alerts.py`), así que el
 * peor caso son ~4 h. El proyecto ya retiró «tiempo real» del login por esta
 * misma razón; el valor del contrato se queda como está y solo cambia lo que
 * lee el usuario.
 */
export const FREQ_LABEL: Record<Frequency, string> = {
  immediate: "En cuanto se detecte (hasta ~4 h)",
  daily: "Diaria",
  weekly: "Semanal",
};

export const FREQ_OPTIONS: { value: Frequency; label: string }[] = [
  { value: "immediate", label: FREQ_LABEL.immediate },
  { value: "daily", label: FREQ_LABEL.daily },
  { value: "weekly", label: FREQ_LABEL.weekly },
];

/**
 * Bandas del Radar como umbral mínimo. El texto explica lo que el nombre de la
 * banda no dice: elegir una acota además al universo puntuable —abiertas y en
 * plazo—, que es el conjunto sobre el que el Radar calcula esa banda.
 */
export const BANDA_OPTIONS: { value: string; label: string }[] = [
  { value: "__any__", label: "— Cualquiera —" },
  { value: "Tibia", label: "Tibia o mejor" },
  { value: "Atractiva", label: "Atractiva o mejor" },
  { value: "Caliente", label: "Solo Caliente" },
];

/**
 * Procedimientos y tipos de contrato que persiste la ingesta (revisión `v85`).
 * No salen de `/meta/filters` —ese catálogo solo publica estado, CCAA,
 * tecnología y CPV— así que aquí son las etiquetas del selector, no datos
 * derivados: el filtro real lo aplica el backend contra la columna.
 */
export const PROCEDIMIENTO_OPTIONS = ["abierto", "restringido", "negociado", "menor"];

export const TIPO_CONTRATO_OPTIONS = ["servicios", "suministros", "obras"];

/**
 * Nota bajo el selector: la latencia es de la ingesta, no de la frecuencia
 * elegida, y para un plazo que vence hoy ninguna frecuencia es suficiente.
 */
export const FREQ_NOTE =
  "TenderFlow revisa las fuentes cada 4 horas: ninguna frecuencia entrega antes. Para un plazo que vence hoy, la fuente oficial sigue siendo el perfil del contratante.";

/**
 * Lista de CCAA del selector: las de `meta/filters` si llegaron, y si no el
 * fallback local. La opción «— Todas —` (`__all__`) va siempre delante.
 */
export function ccaaOptions(metaCcaas: string[] | undefined): string[] {
  return metaCcaas && metaCcaas.length > 0 ? ["__all__", ...metaCcaas] : CCAA_FALLBACK;
}
