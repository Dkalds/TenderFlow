"use client";

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  ThumbsUp,
  ThumbsDown,
  SkipForward,
  Info,
  Activity,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  X,
} from "lucide-react";
import { formatCurrency, formatNumber, formatPercent, cn } from "@/lib/utils";
import { apiMutate } from "@/lib/api-client";

interface TechModel {
  tech_scores: Record<string, number>;
  tech_predicted: string[];
  tech_principal: string | null;
  tech_max_proba: number;
  tech_thresholds: Record<string, number>;
}

interface QueueItem {
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
  [key: string]: unknown;
}

interface QueueResponse {
  items?: QueueItem[];
  total?: number;
}

interface FeedbackStats {
  total_labels?: number;
  pct_relevant?: number;
  last_updated?: string;
  [key: string]: unknown;
}

interface ModelVersionInfo {
  version: number;
  trained_at: string | null;
  metrics: Record<string, number>;
  trained_on_n_feedbacks?: number | null;
}

interface ModelInfo {
  active: ModelVersionInfo | null;
  feedbacks_since_train: number;
  history: { version: number; trained_at: string | null; metrics: Record<string, number> }[];
}

type Strategy = "uncertainty" | "random";

function headlineMetric(metrics: Record<string, number>): { label: string; value: number } | null {
  for (const key of ["pr_auc", "f1", "accuracy", "precision", "recall"]) {
    if (typeof metrics[key] === "number") return { label: key, value: metrics[key] };
  }
  return null;
}

export default function ActiveLearningPage() {
  const queryClient = useQueryClient();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [expandedNotes, setExpandedNotes] = useState<Set<string>>(new Set());
  const [expandedDesc, setExpandedDesc] = useState<Set<string>>(new Set());
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [strategy, setStrategy] = useState<Strategy>("uncertainty");
  const [selectedTech, setSelectedTech] = useState<Record<string, string | null>>({});
  const [secondaryTechs, setSecondaryTechs] = useState<Record<string, Set<string>>>({});

  const { data: queue, isLoading: queueLoading, isError: queueError } = useQuery<QueueResponse>({
    queryKey: ["feedback-queue", strategy],
    queryFn: async () => {
      const res = await fetch(
        `/api/v1/feedback/queue?strategy=${strategy}&limit=20`,
        { credentials: "include" },
      );
      if (res.status === 401) throw new Error("Sesion expirada");
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.json();
    },
  });

  const { data: modelInfo } = useQuery<ModelInfo>({
    queryKey: ["feedback-model-info"],
    queryFn: async () => {
      const res = await fetch("/api/v1/feedback/model-info", { credentials: "include" });
      if (res.status === 401) throw new Error("Sesion expirada");
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.json();
    },
  });

  const { data: stats, isLoading: statsLoading } = useQuery<FeedbackStats>({
    queryKey: ["feedback-stats"],
    queryFn: async () => {
      const res = await fetch("/api/v1/feedback/stats", {
        credentials: "include",
      });
      if (res.status === 401) throw new Error("Sesion expirada");
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.json();
    },
  });

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
      queryClient.invalidateQueries({ queryKey: ["feedback-stats"] });
    },
    onError: () => {
      toast.error("Error al enviar feedback. Intenta de nuevo.");
    },
  });

  const items = queue?.items ?? [];
  const pendingItems = items.filter((it) => !dismissed.has(it.id_externo));
  const queueSize = queue?.total ?? items.length;

  const techCounts: Record<string, number> = {};
  for (const item of items) {
    const principal = item.model?.tech_principal ?? item.tecnologia;
    if (principal) {
      techCounts[principal] = (techCounts[principal] ?? 0) + 1;
    }
  }
  const hasTechData = Object.keys(techCounts).length > 0;

  const activeModel = modelInfo?.active ?? null;
  const metric = activeModel ? headlineMetric(activeModel.metrics) : null;
  const prevMetric =
    metric && modelInfo && modelInfo.history.length > 1
      ? modelInfo.history[1]?.metrics?.[metric.label]
      : undefined;
  const metricTrend =
    metric && typeof prevMetric === "number" ? metric.value - prevMetric : null;

  const handleConfirmLabel = useCallback(
    (expediente: string) => {
      const tech = selectedTech[expediente] ?? null;
      const secs = secondaryTechs[expediente]
        ? Array.from(secondaryTechs[expediente]!)
        : [];
      submitFeedback.mutate({
        expediente,
        relevante: true,
        nota: notes[expediente],
        tecnologia: tech,
        tecnologias_secundarias: secs,
      });
    },
    [selectedTech, secondaryTechs, notes, submitFeedback],
  );

  const handleNotRelevant = useCallback(
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

  const handleSkip = useCallback(
    (expediente: string) => {
      setDismissed((prev) => new Set(prev).add(expediente));
    },
    [],
  );

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

  const selectTech = useCallback(
    (expediente: string, tech: string, shiftKey: boolean) => {
      if (shiftKey) {
        setSecondaryTechs((prev) => {
          const current = new Set(prev[expediente] ?? []);
          if (current.has(tech)) current.delete(tech);
          else current.add(tech);
          return { ...prev, [expediente]: current };
        });
      } else {
        setSelectedTech((prev) => {
          const current = prev[expediente];
          if (current === tech) {
            return { ...prev, [expediente]: null };
          }
          return { ...prev, [expediente]: tech };
        });
        setSecondaryTechs((prev) => {
          const s = prev[expediente] ?? new Set();
          s.delete(tech);
          return { ...prev, [expediente]: s };
        });
      }
    },
    [],
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="sr-only">Active Learning</h1>
        <p className="text-muted-foreground">
          Etiquetado de muestras con alta incertidumbre del modelo ML.
        </p>
      </div>

      {/* Explanation */}
      <Card className="bg-blue-50/50 dark:bg-blue-950/20 border-blue-200 dark:border-blue-800">
        <CardContent className="pt-4 flex items-start gap-2 text-sm">
          <Info className="h-4 w-4 text-blue-600 shrink-0 mt-0.5" />
          <span>
            Etiquetado humano de licitaciones en la zona de incertidumbre del
            modelo ML para mejorar la precision del clasificador. Las
            oportunidades se seleccionan mediante muestreo por incertidumbre
            (uncertainty sampling). Selecciona la tecnologia principal haciendo
            click en el chip; usa shift-click para marcar tecnologias
            secundarias.
          </span>
        </CardContent>
      </Card>

      {/* Stats KPIs */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="pt-6 text-center">
            {statsLoading ? (
              <Skeleton className="h-8 w-16 mx-auto" />
            ) : (
              <p className="text-2xl font-bold">
                {formatNumber(stats?.total_labels)}
              </p>
            )}
            <p className="text-sm text-muted-foreground">
              Etiquetas totales
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6 text-center">
            {statsLoading ? (
              <Skeleton className="h-8 w-16 mx-auto" />
            ) : (
              <p className="text-2xl font-bold">
                {stats?.pct_relevant != null
                  ? formatPercent(stats.pct_relevant)
                  : "—"}
              </p>
            )}
            <p className="text-sm text-muted-foreground">% Relevantes</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6 text-center">
            {queueLoading ? (
              <Skeleton className="h-8 w-16 mx-auto" />
            ) : (
              <p className="text-2xl font-bold">{formatNumber(queueSize)}</p>
            )}
            <p className="text-sm text-muted-foreground">En cola</p>
          </CardContent>
        </Card>
      </div>

      {/* Model info card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="h-4 w-4" />
            Modelo de clasificacion
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-3 text-sm">
            <div>
              <p className="text-muted-foreground">Total etiquetas</p>
              <p className="font-medium">
                {formatNumber(stats?.total_labels)}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground">
                Precision estimada (% relevante)
              </p>
              <p className="font-medium">
                {stats?.pct_relevant != null
                  ? formatPercent(stats.pct_relevant)
                  : "—"}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground">Ultima actualizacion</p>
              <p className="font-medium">
                {stats?.last_updated
                  ? new Date(stats.last_updated).toLocaleString("es-ES")
                  : "—"}
              </p>
            </div>
          </div>

          {activeModel ? (
            <>
              <Separator className="my-4" />
              <div className="grid gap-4 sm:grid-cols-4 text-sm">
                <div>
                  <p className="text-muted-foreground">Modelo activo</p>
                  <p className="font-medium tabular-nums">v{activeModel.version}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Reentrenado</p>
                  <p className="font-medium">
                    {activeModel.trained_at
                      ? new Date(activeModel.trained_at).toLocaleDateString("es-ES")
                      : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">
                    {metric ? metric.label.toUpperCase() : "Metrica"}
                  </p>
                  <p className="font-medium tabular-nums">
                    {metric ? metric.value.toFixed(3) : "—"}
                    {metricTrend != null && metricTrend !== 0 && (
                      <span
                        className={cn(
                          "ml-1 text-xs",
                          metricTrend > 0 ? "text-green-600" : "text-red-600",
                        )}
                      >
                        {metricTrend > 0 ? "▲" : "▼"} {Math.abs(metricTrend).toFixed(3)}
                      </span>
                    )}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">Etiquetas desde el reentreno</p>
                  <p className="font-medium tabular-nums">
                    {formatNumber(modelInfo?.feedbacks_since_train ?? 0)}
                  </p>
                </div>
              </div>
            </>
          ) : (
            <p className="mt-3 text-xs text-muted-foreground">
              Aun no hay un modelo registrado; etiqueta para habilitar el primer
              entrenamiento.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Technology chips */}
      {hasTechData && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tecnologias en cola</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {Object.entries(techCounts).map(([tech, count]) => (
                <Badge key={tech} variant="outline" className="text-sm py-1 px-3">
                  {tech}: {count}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Separator />

      {/* Progress */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Activity className="h-4 w-4" />
        <span>
          {dismissed.size} de {items.length} items revisados en esta sesion
        </span>
        {items.length > 0 && (
          <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden max-w-xs">
            <div
              className="h-full bg-primary rounded-full transition-[width]"
              style={{
                width: `${Math.min((dismissed.size / items.length) * 100, 100)}%`,
              }}
            />
          </div>
        )}
      </div>

      {/* Labeling queue */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-semibold">Cola de etiquetado</h2>
        <div className="flex items-center gap-1" role="group" aria-label="Estrategia de muestreo">
          <span className="mr-1 text-xs text-muted-foreground">Estrategia:</span>
          <Button
            size="sm"
            variant={strategy === "uncertainty" ? "default" : "outline"}
            onClick={() => setStrategy("uncertainty")}
          >
            Incertidumbre
          </Button>
          <Button
            size="sm"
            variant={strategy === "random" ? "default" : "outline"}
            onClick={() => setStrategy("random")}
          >
            Aleatoria
          </Button>
        </div>
      </div>

      {queueError && (
        <Card className="border-destructive">
          <CardContent className="pt-6 text-destructive">
            Error al cargar cola de feedback. Verifica que la API este activa.
          </CardContent>
        </Card>
      )}

      {queueLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardContent className="pt-6 space-y-2">
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-4 w-1/4" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {!queueLoading && pendingItems.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="py-12 text-center">
            <Activity className="h-12 w-12 text-muted-foreground/50 mx-auto mb-4" />
            <p className="text-lg font-medium text-muted-foreground">
              {items.length === 0
                ? "No hay items en la cola de feedback"
                : "Has revisado todos los items de esta sesion"}
            </p>
          </CardContent>
        </Card>
      )}

      {!queueLoading && (
        <div className="space-y-3">
          {pendingItems.map((item) => {
            const prob = item.confidence ?? null;
            const noteExpanded = expandedNotes.has(item.id_externo);
            const descExpanded = expandedDesc.has(item.id_externo);
            const model = item.model;
            const chosenTech = selectedTech[item.id_externo] ?? null;
            const chosenSecs = secondaryTechs[item.id_externo] ?? new Set<string>();
            const hasSelection = chosenTech != null;

            const sortedScores = model
              ? Object.entries(model.tech_scores).sort(([, a], [, b]) => b - a)
              : [];

            return (
              <Card key={item.id_externo}>
                <CardContent className="pt-4 space-y-3">
                  {/* Header: titulo + link + badges */}
                  <div>
                    <div className="flex items-start gap-2">
                      <p className="font-medium leading-snug flex-1">
                        {item.url_origen ? (
                          <a
                            href={item.url_origen}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="hover:underline"
                          >
                            {item.titulo ?? "Sin titulo"}
                            <ExternalLink className="inline h-3 w-3 ml-1 text-muted-foreground" />
                          </a>
                        ) : (
                          item.titulo ?? "Sin titulo"
                        )}
                      </p>
                    </div>
                    <p className="text-xs text-muted-foreground font-mono mt-0.5">
                      {item.id_externo}
                    </p>
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {item.organo && (
                        <Badge variant="outline" className="text-xs">
                          {item.organo}
                        </Badge>
                      )}
                      {item.ccaa && (
                        <Badge variant="outline" className="text-xs">
                          {item.ccaa}
                        </Badge>
                      )}
                      {item.cpv && (
                        <Badge variant="secondary" className="text-xs font-mono">
                          CPV {item.cpv}
                        </Badge>
                      )}
                      {item.importe != null && (
                        <Badge variant="outline" className="text-xs">
                          {formatCurrency(item.importe)}
                        </Badge>
                      )}
                      {item.fecha_publicacion && (
                        <Badge variant="outline" className="text-xs">
                          {new Date(item.fecha_publicacion).toLocaleDateString("es-ES")}
                        </Badge>
                      )}
                      {item.tecnologia && (
                        <Badge variant="outline" className="text-xs border-blue-300 text-blue-700 dark:text-blue-400 dark:border-blue-700">
                          {item.tecnologia}
                        </Badge>
                      )}
                    </div>
                  </div>

                  {/* Descripcion colapsable */}
                  {item.descripcion && (
                    <div>
                      <button
                        type="button"
                        className="text-xs text-muted-foreground hover:underline flex items-center gap-1"
                        onClick={() => toggleDesc(item.id_externo)}
                      >
                        {descExpanded ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        )}
                        {descExpanded ? "Ocultar descripcion" : "Ver descripcion"}
                      </button>
                      {descExpanded && (
                        <p className="text-sm text-muted-foreground mt-1 whitespace-pre-line">
                          {item.descripcion}
                        </p>
                      )}
                    </div>
                  )}

                  {/* Binary confidence (backward compat) */}
                  {prob != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">
                        Confianza SAP (binario):
                      </span>
                      <div className="flex-1 h-2 max-w-[200px] rounded-full bg-muted overflow-hidden">
                        <div
                          className={cn(
                            "h-full rounded-full transition-[width]",
                            prob >= 0.7
                              ? "bg-green-500"
                              : prob >= 0.4
                                ? "bg-yellow-500"
                                : "bg-red-500",
                          )}
                          style={{
                            width: `${Math.min(prob * 100, 100)}%`,
                          }}
                        />
                      </div>
                      <span className="text-xs font-medium">
                        {(prob * 100).toFixed(1)}%
                      </span>
                    </div>
                  )}

                  {/* Tech scores block */}
                  {model && sortedScores.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-xs font-medium text-muted-foreground">
                          Prediccion del modelo
                        </span>
                        {activeModel && (
                          <span
                            className="text-xs text-muted-foreground/70"
                            title={`Modelo v${activeModel.version}${
                              activeModel.trained_at
                                ? ` — reentrenado ${new Date(activeModel.trained_at).toLocaleDateString("es-ES")}`
                                : ""
                            }`}
                          >
                            (v{activeModel.version})
                          </span>
                        )}
                      </div>
                      <div className="space-y-1.5">
                        {sortedScores.map(([tech, score]) => {
                          const threshold = model.tech_thresholds[tech] ?? 0.5;
                          const isPredicted = model.tech_predicted.includes(tech);
                          const isPrincipal = model.tech_principal === tech;
                          const isSelected = chosenTech === tech;
                          const isSecondary = chosenSecs.has(tech);

                          return (
                            <button
                              key={tech}
                              type="button"
                              onClick={(e) =>
                                selectTech(item.id_externo, tech, e.shiftKey)
                              }
                              className={cn(
                                "w-full flex items-center gap-2 px-2 py-1 rounded-md text-sm transition-colors",
                                "hover:bg-muted/70 focus:outline-none focus:ring-1 focus:ring-ring",
                                isSelected && "ring-2 ring-primary bg-primary/5",
                                isSecondary && !isSelected && "ring-1 ring-blue-400 bg-blue-50/50 dark:bg-blue-950/20",
                              )}
                              title={`Score: ${(score * 100).toFixed(1)}% — Umbral: ${(threshold * 100).toFixed(0)}%${
                                isPrincipal ? " (principal)" : ""
                              }${isSelected ? " [seleccionada]" : ""}${
                                isSecondary ? " [secundaria]" : ""
                              }`}
                            >
                              <span
                                className={cn(
                                  "w-[72px] shrink-0 text-xs font-mono font-medium text-left",
                                  isPrincipal && "text-green-700 dark:text-green-400",
                                  isSelected && "text-primary font-bold",
                                  isSecondary && !isSelected && "text-blue-600 dark:text-blue-400",
                                )}
                              >
                                {tech}
                              </span>
                              <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                                <div
                                  className={cn(
                                    "h-full rounded-full transition-[width]",
                                    isSelected
                                      ? "bg-primary"
                                      : isSecondary
                                        ? "bg-blue-400"
                                        : score >= threshold
                                          ? "bg-green-500"
                                          : "bg-muted-foreground/30",
                                  )}
                                  style={{
                                    width: `${Math.min(score * 100, 100)}%`,
                                  }}
                                />
                                {threshold > 0 && threshold < 1 && (
                                  <div
                                    className="absolute top-0 h-full w-px bg-red-500/60"
                                    style={{
                                      left: `${threshold * 100}%`,
                                      height: "8px",
                                      position: "relative",
                                      marginTop: "-8px",
                                    }}
                                    title={`Umbral: ${(threshold * 100).toFixed(0)}%`}
                                  />
                                )}
                              </div>
                              <span className="text-xs tabular-nums w-[42px] text-right shrink-0">
                                {(score * 100).toFixed(0)}%
                              </span>
                              {isPredicted && !isSelected && !isSecondary && (
                                <span
                                  className="text-[10px] text-green-600 dark:text-green-400 shrink-0"
                                  title="Supera el umbral del modelo"
                                >
                                  ✓
                                </span>
                              )}
                              {isSelected && (
                                <span className="text-[10px] text-primary shrink-0 font-bold">
                                  ●
                                </span>
                              )}
                              {isSecondary && !isSelected && (
                                <span className="text-[10px] text-blue-500 shrink-0 font-bold">
                                  ○
                                </span>
                              )}
                            </button>
                          );
                        })}
                      </div>
                      <p className="text-[10px] text-muted-foreground/60 mt-1">
                        Click = principal · Shift+click = secundaria · ▎marca = umbral del modelo
                      </p>
                    </div>
                  )}

                  {/* No model available */}
                  {!model && prob == null && (
                    <p className="text-xs text-muted-foreground italic">
                      Sin prediccion del modelo disponible.
                    </p>
                  )}

                  {/* Action buttons */}
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Button
                      size="sm"
                      className="bg-green-600 hover:bg-green-700"
                      onClick={() => handleConfirmLabel(item.id_externo)}
                      disabled={submitFeedback.isPending || !hasSelection}
                      title={
                        hasSelection
                          ? `Confirmar: ${chosenTech}${
                              chosenSecs.size
                                ? ` + ${Array.from(chosenSecs).join(", ")}`
                                : ""
                            }`
                          : "Selecciona una tecnologia primero"
                      }
                    >
                      <ThumbsUp className="mr-1 h-4 w-4" />
                      {hasSelection
                        ? `Confirmar: ${chosenTech}`
                        : "Confirmar etiqueta"}
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => handleNotRelevant(item.id_externo)}
                      disabled={submitFeedback.isPending}
                      title="Ninguna tecnologia / no relevante"
                    >
                      <ThumbsDown className="mr-1 h-4 w-4" />
                      Ninguna / no relevante
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleSkip(item.id_externo)}
                    >
                      <SkipForward className="mr-1 h-4 w-4" />
                      Saltar
                    </Button>
                    {chosenTech && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-xs"
                        onClick={() => {
                          setSelectedTech((prev) => ({
                            ...prev,
                            [item.id_externo]: null,
                          }));
                          setSecondaryTechs((prev) => ({
                            ...prev,
                            [item.id_externo]: new Set(),
                          }));
                        }}
                        title="Limpiar seleccion"
                      >
                        <X className="mr-1 h-3 w-3" />
                        Limpiar
                      </Button>
                    )}
                  </div>

                  {/* Note toggle */}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs"
                    onClick={() => toggleNote(item.id_externo)}
                  >
                    {noteExpanded ? (
                      <ChevronUp className="mr-1 h-3 w-3" />
                    ) : (
                      <ChevronDown className="mr-1 h-3 w-3" />
                    )}
                    Nota
                  </Button>
                  {noteExpanded && (
                    <Textarea
                      className="mt-2 w-full"
                      placeholder="Nota opcional..."
                      rows={2}
                      value={notes[item.id_externo] ?? ""}
                      onChange={(e) =>
                        setNotes((prev) => ({
                          ...prev,
                          [item.id_externo]: e.target.value,
                        }))
                      }
                    />
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
