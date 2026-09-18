/**
 * F4.1 — el valor ponderado del pipeline, con sus supuestos a la vista.
 *
 * El número lo calcula el backend (`PursuitMetrics.pipeline_value_eur`): suma
 * de importe × probabilidad de etapa sobre las oportunidades **abiertas**.
 * Viaja con las probabilidades que usó y con cuántas oportunidades quedaron
 * fuera por no tener importe publicado. Aquí sólo se ordena eso para
 * pintarlo: un valor ponderado sin sus supuestos no es reproducible, y
 * ADR-014 pide que lo sea.
 */
import type { PursuitMetrics } from "@/lib/api-types";

/** Orden del workflow: los supuestos se leen de la etapa más temprana a la más tardía. */
const ORDEN_ETAPAS = ["identified", "qualifying", "go_no_go", "preparing", "submitted"] as const;

const ETIQUETA_ETAPA: Record<string, string> = {
  identified: "Identificada",
  qualifying: "En cualificación",
  go_no_go: "Decisión",
  preparing: "Preparando oferta",
  submitted: "Presentada",
};

export interface SupuestoEtapa {
  etapa: string;
  etiqueta: string;
  probabilidad: number;
}

/** Probabilidades que el backend **usó** (sólo etapas con oportunidades abiertas). */
export function supuestosEtapas(metrics: PursuitMetrics): SupuestoEtapa[] {
  const usadas = metrics.probabilidades_etapa_usadas ?? {};
  const posicion = (etapa: string) => {
    const i = (ORDEN_ETAPAS as readonly string[]).indexOf(etapa);
    return i === -1 ? ORDEN_ETAPAS.length : i;
  };
  return Object.entries(usadas)
    .map(([etapa, probabilidad]) => ({
      etapa,
      etiqueta: ETIQUETA_ETAPA[etapa] ?? etapa,
      probabilidad,
    }))
    .sort((a, b) => posicion(a.etapa) - posicion(b.etapa));
}

export interface TrimestrePrevision {
  clave: string;
  etiqueta: string;
  valor: number;
}

/** `2026-Q4` → «T4 2026»; cualquier otra clave se deja tal cual. */
export function etiquetaTrimestre(clave: string): string {
  const match = /^(\d{4})-Q([1-4])$/.exec(clave);
  return match ? `T${match[2]} ${match[1]}` : clave;
}

/** Previsión por trimestre en orden cronológico. */
export function previsionOrdenada(metrics: PursuitMetrics): TrimestrePrevision[] {
  return Object.entries(metrics.prevision_trimestral ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([clave, valor]) => ({ clave, etiqueta: etiquetaTrimestre(clave), valor }));
}
