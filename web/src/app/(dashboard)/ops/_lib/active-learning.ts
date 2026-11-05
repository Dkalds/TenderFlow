/**
 * Formas de la cola de active learning y la métrica destacada del modelo.
 *
 * Viven fuera de `_hooks/use-active-learning.ts` para que el hook quepa en las
 * 300 líneas de `src/app/**` (ver `eslint.config.mjs`): el hook guarda el
 * estado y las llamadas; aquí solo hay tipos y una función pura.
 */

import type { Schemas } from "@/lib/api-types";

/** Lo que el clasificador dijo de un expediente de la cola. */
export type TechModel = Schemas["QueueModelBlock"];

/** Lo que propone el LLM para un expediente de la cola por desacuerdo. */
export type LlmProposal = Schemas["QueueLlmBlock"];

/** Una etiqueta de la taxonomía (`GET /feedback/taxonomia`): código, nombre y nivel. */
export type EtiquetaTaxonomia = Schemas["EtiquetaTaxonomia"];

/**
 * Un expediente de `GET /feedback/queue`. `motivo` y `llm` solo llegan en la
 * cola por desacuerdo; con `sin_confianza` el modelo no puntuó la licitación y
 * `confidence` es relleno, no un dato.
 */
export type QueueItem = Schemas["FeedbackQueueItem"];

/**
 * Si la confianza del clasificador SAP es una señal (D55): solo con una versión
 * activa que haya pasado el gate. Sin ella, los ítems llegan con `sin_confianza`.
 */
export type SenalClasificador = Schemas["SenalClasificadorDTO"];

export type QueueResponse = Schemas["FeedbackQueueResult"];

export type ModelInfo = Schemas["ModelInfoResult"];

/** La versión activa del modelo, tal como la pinta la consola. */
export interface ModelVersionInfo {
  version: number | string;
  trained_at: string | null;
  metrics: Record<string, number>;
  trained_on_n_feedbacks?: number | null;
}

/** Solo las métricas numéricas: el registro las guarda como un dict libre. */
function metricasNumericas(valor: unknown): Record<string, number> {
  if (typeof valor !== "object" || valor === null) return {};
  return Object.fromEntries(
    Object.entries(valor as Record<string, unknown>).filter(
      (par): par is [string, number] => typeof par[1] === "number",
    ),
  );
}

/** La versión activa de `/feedback/model-info`, con solo sus métricas numéricas. */
export function leerModeloActivo(active: ModelInfo["active"] | undefined): ModelVersionInfo | null {
  if (!active) return null;
  return {
    version: active.version,
    trained_at: active.trained_at,
    metrics: metricasNumericas(active.metrics),
    trained_on_n_feedbacks: active.trained_on_n_feedbacks ?? null,
  };
}

export type Strategy = "desacuerdo" | "uncertainty" | "random";

/** Métrica destacada del modelo activo, en el orden de preferencia histórico. */
export interface HeadlineMetric {
  label: string;
  value: number;
}

export function headlineMetric(metrics: Record<string, number>): HeadlineMetric | null {
  for (const key of ["pr_auc", "f1", "accuracy", "precision", "recall"]) {
    if (typeof metrics[key] === "number") return { label: key, value: metrics[key] };
  }
  return null;
}

/*
 * La selección de familias y fabricantes de un expediente es una lista
 * ordenada: la primera etiqueta viaja como `tecnologia` (la principal) y el
 * resto como `tecnologias_secundarias`, que es lo que ya acepta
 * `POST /feedback`.
 */

/** Con qué arranca la selección: las etiquetas que propone el LLM, si hay. */
export function seleccionInicial(item: QueueItem | undefined): string[] {
  return [...(item?.llm?.familias ?? [])];
}

/** Marca `codigo` al final o lo desmarca; con la lista vacía, queda de principal. */
export function alternarEtiqueta(seleccion: readonly string[], codigo: string): string[] {
  return seleccion.includes(codigo) ? seleccion.filter((c) => c !== codigo) : [...seleccion, codigo];
}

/** El clic en un chip del modelo: `codigo` pasa a principal; si ya lo era, sale. */
export function hacerPrincipal(seleccion: readonly string[], codigo: string): string[] {
  if (seleccion[0] === codigo) return seleccion.slice(1);
  return [codigo, ...seleccion.filter((c) => c !== codigo)];
}
