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

/**
 * Consultas de ejemplo. Cada una enseña una cosa que la caja entiende: un
 * filtro escrito en la frase, un importe, una búsqueda dentro de los pliegos,
 * el orden por fecha y una pregunta al asistente. Las anteriores prometían lo
 * que la búsqueda no hacía: tres de las cinco no devolvían ni un resultado.
 */
export const EJEMPLOS = [
  "mantenimiento SAP abiertas en Andalucía",
  "licencias de más de 500.000 € desde 2026",
  "baja temeraria",
  "últimas licitaciones de S/4HANA",
  "¿Qué es un PCAP y qué contiene?",
];

/** Lo que admite el deslizador «Resultados»: la primera tanda de una búsqueda. */
export const MIN_TOP_K = 1;
export const MAX_TOP_K = 50;

function enRango(valor: unknown, minimo: number, maximo: number, defecto: number): number {
  return typeof valor === "number" && Number.isFinite(valor) ? Math.min(maximo, Math.max(minimo, valor)) : defecto;
}

/**
 * Los ajustes guardados, con cada campo validado. `localStorage` lo escribe
 * cualquiera —otra versión de la consola, una extensión, la mano de quien
 * depura— y un `topK` de 500 guardado era un 422 en cada búsqueda, para
 * siempre, sin forma de arreglarlo desde la pantalla.
 */
export function loadConfig(): InvestigadorConfig {
  const raw = getJSON<Partial<Record<keyof InvestigadorConfig, unknown>>>(CONFIG_KEY, {});
  return {
    topK: Math.round(enRango(raw.topK, MIN_TOP_K, MAX_TOP_K, DEFAULT_CONFIG.topK)),
    alpha: enRango(raw.alpha, 0, 1, DEFAULT_CONFIG.alpha),
    model: typeof raw.model === "string" ? raw.model : DEFAULT_CONFIG.model,
    useGlobalFilters:
      typeof raw.useGlobalFilters === "boolean" ? raw.useGlobalFilters : DEFAULT_CONFIG.useGlobalFilters,
  };
}

export function saveConfig(cfg: InvestigadorConfig) {
  setJSON(CONFIG_KEY, cfg);
}

export function loadHistory(): string[] {
  const raw = getJSON<unknown>(HISTORY_KEY, []);
  return Array.isArray(raw) ? raw.filter((h): h is string => typeof h === "string").slice(0, MAX_HISTORY) : [];
}

export function saveHistory(h: string[]) {
  setJSON(HISTORY_KEY, h);
}
