/**
 * Persistencia local de la consola del Investigador: ajustes e historial.
 *
 * Solo `localStorage` (vía `@/lib/storage`, que tolera su ausencia). Se lee
 * después del montaje, nunca durante el render del servidor: leerlo antes
 * rompía la hidratación.
 */

import { getJSON, setJSON } from "@/lib/storage";
import type { InvestigadorConfig } from "./types";

const CONFIG_KEY = "investigador_config";
const HISTORY_KEY = "search_history";

/** Tamaño máximo del historial de consultas que se recuerda. */
export const MAX_HISTORY = 10;

export const DEFAULT_CONFIG: InvestigadorConfig = {
  topK: 10,
  model: "",
  alpha: 0.7,
  useGlobalFilters: false,
};

export const EXAMPLE_QUESTIONS = [
  "¿Cuáles son las licitaciones más recientes?",
  "¿Qué es un PCAP y qué contiene?",
  "¿Cómo funciona el procedimiento abierto simplificado?",
  "Resumen de licitaciones de mantenimiento en Madrid",
  "Buscar licitaciones de S/4HANA con importe mayor a 500K",
];

export function loadConfig(): InvestigadorConfig {
  const raw = getJSON<Partial<InvestigadorConfig>>(CONFIG_KEY, {});
  return { ...DEFAULT_CONFIG, ...raw };
}

export function saveConfig(cfg: InvestigadorConfig) {
  setJSON(CONFIG_KEY, cfg);
}

export function loadHistory(): string[] {
  return getJSON<string[]>(HISTORY_KEY, []);
}

export function saveHistory(h: string[]) {
  setJSON(HISTORY_KEY, h);
}
