/**
 * Formas de la cola de active learning y la métrica destacada del modelo.
 *
 * Viven fuera de `_hooks/use-active-learning.ts` para que el hook quepa en las
 * 300 líneas de `src/app/**` (ver `eslint.config.mjs`): el hook guarda el
 * estado y las llamadas; aquí solo hay tipos y una función pura.
 */

import type { Schemas } from "@/lib/api-types";

export interface TechModel {
  tech_scores: Record<string, number>;
  tech_predicted: string[];
  tech_principal: string | null;
  tech_max_proba: number;
  tech_thresholds: Record<string, number>;
}

/** Lo que propone el LLM para un expediente de la cola por desacuerdo. */
export type LlmProposal = Schemas["QueueLlmBlock"];

export interface QueueItem {
  id_externo: string;
  titulo?: string;
  descripcion?: string;
  cpv?: string | null;
  importe?: number | null;
  organo?: string | null;
  ccaa?: string | null;
  fecha_publicacion?: string | null;
  url_origen?: string | null;
  confidence?: number;
  uncertainty?: number;
  tecnologia?: string | null;
  model?: TechModel | null;
  /** Solo en la cola por desacuerdo: por qué está el expediente en ella. */
  motivo?: string | null;
  /** Solo en la cola por desacuerdo: la propuesta del LLM. */
  llm?: LlmProposal | null;
  [key: string]: unknown;
}

export interface QueueResponse {
  items?: QueueItem[];
  total?: number;
}

export interface ModelVersionInfo {
  version: number;
  trained_at: string | null;
  metrics: Record<string, number>;
  trained_on_n_feedbacks?: number | null;
}

export interface ModelInfo {
  active: ModelVersionInfo | null;
  feedbacks_since_train: number;
  history: { version: number; trained_at: string | null; metrics: Record<string, number> }[];
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
