"use client";

/**
 * Estado y datos de la cola de active learning.
 *
 * Todo lo que la vista necesita saber (cola, modelo activo, estadísticas) y
 * todo lo que sabe hacer (etiquetar, descartar, saltar, anotar) vive aquí; los
 * componentes de `_components/active-learning/` solo pintan lo que este hook
 * devuelve. La selección de familias y fabricantes es por expediente, no por
 * tarjeta, porque la confirmación manda principal y secundarias juntas; la
 * lleva `use-seleccion-etiquetas.ts`. Las formas (ítem, modelo, estrategia)
 * viven en `_lib/active-learning.ts`.
 */

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { feedbackKeys } from "@/lib/query-keys";
import { useFeedbackStats, useTaxonomiaTecnologias, type FeedbackStats } from "@/hooks/use-feedback";
import {
  headlineMetric,
  type EtiquetaTaxonomia,
  type HeadlineMetric,
  type ModelInfo,
  type ModelVersionInfo,
  type QueueItem,
  type QueueResponse,
  type Strategy,
} from "../_lib/active-learning";
import { useSeleccionEtiquetas, type SeleccionEtiquetas } from "./use-seleccion-etiquetas";

export interface ActiveLearning extends SeleccionEtiquetas {
  items: QueueItem[];
  pendingItems: QueueItem[];
  queueSize: number;
  queueLoading: boolean;
  /** Lo que lanzó la consulta de la cola (`null` sin fallo), para `PanelError`. */
  queueError: unknown;
  retryQueue: () => void;
  dismissedCount: number;
  strategy: Strategy;
  setStrategy: (strategy: Strategy) => void;
  stats: FeedbackStats | undefined;
  statsLoading: boolean;
  activeModel: ModelVersionInfo | null;
  metric: HeadlineMetric | null;
  metricTrend: number | null;
  feedbacksSinceTrain: number;
  techCounts: Record<string, number>;
  hasTechData: boolean;
  notes: Record<string, string>;
  expandedNotes: Set<string>;
  expandedDesc: Set<string>;
  /** Familias y fabricantes que se pueden elegir (la taxonomía entera). */
  taxonomia: EtiquetaTaxonomia[];
  isSubmitting: boolean;
  setNote: (expediente: string, value: string) => void;
  toggleNote: (expediente: string) => void;
  toggleDesc: (expediente: string) => void;
  confirmLabel: (expediente: string) => void;
  markNotRelevant: (expediente: string) => void;
  /** Envía la propuesta del LLM tal cual; no hace nada si no dijo si es TI. */
  acceptLlmProposal: (expediente: string) => void;
  markTiWithoutFamily: (expediente: string) => void;
  skip: (expediente: string) => void;
}

export function useActiveLearning(): ActiveLearning {
  const queryClient = useQueryClient();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [expandedNotes, setExpandedNotes] = useState<Set<string>>(new Set());
  const [expandedDesc, setExpandedDesc] = useState<Set<string>>(new Set());
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [strategy, setStrategy] = useState<Strategy>("desacuerdo");

  const colaQuery = useQuery<QueueResponse>({
    queryKey: feedbackKeys.queue(strategy),
    queryFn: () => fetchWithAuth<QueueResponse>(`/api/v1/feedback/queue?strategy=${strategy}&limit=20`),
    meta: META_ERROR_EN_LINEA, // el fallo lo pinta la cola (`PanelError`): sin toast encima
  });
  const { data: queue, isLoading: queueLoading } = colaQuery;

  const { data: modelInfo } = useQuery<ModelInfo>({
    queryKey: feedbackKeys.modelInfo,
    queryFn: () => fetchWithAuth<ModelInfo>("/api/v1/feedback/model-info"),
  });

  const { data: stats, isLoading: statsLoading } = useFeedbackStats();
  const { data: taxonomiaData } = useTaxonomiaTecnologias();

  const submitFeedback = useMutation({
    mutationFn: (vars: {
      expediente: string;
      relevante: boolean;
      nota?: string;
      tecnologia?: string | null;
      tecnologias_secundarias?: string[];
    }) =>
      apiMutate("POST", "/api/v1/feedback", {
        expediente: vars.expediente,
        relevante: vars.relevante,
        nota: vars.nota || undefined,
        tecnologia: vars.tecnologia ?? undefined,
        tecnologias_secundarias: vars.tecnologias_secundarias?.length
          ? vars.tecnologias_secundarias
          : undefined,
      }),
    onSuccess: (_data, vars) => {
      setDismissed((prev) => new Set(prev).add(vars.expediente));
      queryClient.invalidateQueries({ queryKey: feedbackKeys.stats });
    },
    onError: () => toast.error("No se pudo guardar la etiqueta. Vuelve a intentarlo."),
  });

  const items = useMemo(() => queue?.items ?? [], [queue]);
  const pendingItems = items.filter((it) => !dismissed.has(it.id_externo));
  const queueSize = queue?.total ?? items.length;
  const { seleccionDe, selectTech, toggleTech, clearSelection } = useSeleccionEtiquetas(items);

  const techCounts: Record<string, number> = {};
  for (const item of items) {
    const principal = item.model?.tech_principal ?? item.tecnologia;
    if (principal) {
      techCounts[principal] = (techCounts[principal] ?? 0) + 1;
    }
  }

  const activeModel = modelInfo?.active ?? null;
  const metric = activeModel ? headlineMetric(activeModel.metrics) : null;
  const prevMetric =
    metric && modelInfo && modelInfo.history.length > 1
      ? modelInfo.history[1]?.metrics?.[metric.label]
      : undefined;
  const metricTrend = metric && typeof prevMetric === "number" ? metric.value - prevMetric : null;

  const confirmLabel = useCallback(
    (expediente: string) => {
      const [principal, ...secundarias] = seleccionDe(expediente);
      submitFeedback.mutate({
        expediente,
        relevante: true,
        nota: notes[expediente],
        tecnologia: principal ?? null,
        tecnologias_secundarias: secundarias,
      });
    },
    [seleccionDe, notes, submitFeedback],
  );

  const markNotRelevant = useCallback(
    (expediente: string) => {
      submitFeedback.mutate({
        expediente,
        relevante: false,
        nota: notes[expediente],
        tecnologia: null,
        tecnologias_secundarias: [],
      });
    },
    [notes, submitFeedback],
  );

  const acceptLlmProposal = useCallback(
    (expediente: string) => {
      const llm = items.find((it) => it.id_externo === expediente)?.llm;
      // Sin respuesta sobre si es TI no hay `relevante` que enviar.
      if (llm == null || llm.es_ti == null) return;
      submitFeedback.mutate({
        expediente,
        relevante: llm.es_ti,
        nota: notes[expediente],
        tecnologia: llm.familias[0] ?? null,
        tecnologias_secundarias: llm.familias.slice(1),
      });
    },
    [items, notes, submitFeedback],
  );

  const markTiWithoutFamily = useCallback(
    (expediente: string) => {
      submitFeedback.mutate({
        expediente,
        relevante: true,
        nota: notes[expediente],
        tecnologia: null,
        tecnologias_secundarias: [],
      });
    },
    [notes, submitFeedback],
  );

  const skip = useCallback((expediente: string) => {
    setDismissed((prev) => new Set(prev).add(expediente));
  }, []);

  const toggleNote = useCallback((expediente: string) => {
    setExpandedNotes((prev) => {
      const next = new Set(prev);
      if (next.has(expediente)) next.delete(expediente);
      else next.add(expediente);
      return next;
    });
  }, []);

  const toggleDesc = useCallback((expediente: string) => {
    setExpandedDesc((prev) => {
      const next = new Set(prev);
      if (next.has(expediente)) next.delete(expediente);
      else next.add(expediente);
      return next;
    });
  }, []);

  const setNote = useCallback((expediente: string, value: string) => {
    setNotes((prev) => ({ ...prev, [expediente]: value }));
  }, []);

  return {
    items,
    pendingItems,
    queueSize,
    queueLoading,
    queueError: colaQuery.error,
    retryQueue: () => void colaQuery.refetch(),
    dismissedCount: dismissed.size,
    strategy,
    setStrategy,
    stats,
    statsLoading,
    activeModel,
    metric,
    metricTrend,
    feedbacksSinceTrain: modelInfo?.feedbacks_since_train ?? 0,
    techCounts,
    hasTechData: Object.keys(techCounts).length > 0,
    notes,
    expandedNotes,
    expandedDesc,
    taxonomia: taxonomiaData?.etiquetas ?? [],
    seleccionDe,
    isSubmitting: submitFeedback.isPending,
    setNote,
    toggleNote,
    toggleDesc,
    selectTech,
    toggleTech,
    clearSelection,
    confirmLabel,
    markNotRelevant,
    acceptLlmProposal,
    markTiWithoutFamily,
    skip,
  };
}
