"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
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
} from "lucide-react";
import { formatNumber, formatPercent, cn } from "@/lib/utils";
import { apiMutate } from "@/lib/api-client";

interface QueueItem {
  expediente: string;
  titulo?: string;
  proba?: number;
  probability?: number;
  tecnologia?: string;
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

export default function ActiveLearningPage() {
  const queryClient = useQueryClient();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [expandedNotes, setExpandedNotes] = useState<Set<string>>(new Set());
  const [notes, setNotes] = useState<Record<string, string>>({});

  const { data: queue, isLoading: queueLoading, isError: queueError } = useQuery<QueueResponse>({
    queryKey: ["feedback-queue"],
    queryFn: async () => {
      const res = await fetch(
        "/api/v1/feedback/queue?strategy=uncertainty&limit=20",
        { credentials: "include" },
      );
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
    mutationFn: (vars: { expediente: string; relevante: boolean; nota?: string }) =>
      apiMutate("POST", "/api/v1/feedback", {
        expediente: vars.expediente,
        relevante: vars.relevante,
        nota: vars.nota || undefined,
      }),
    onSuccess: (_data, vars) => {
      setDismissed((prev) => new Set(prev).add(vars.expediente));
      queryClient.invalidateQueries({ queryKey: ["feedback-stats"] });
    },
    onError: () => {
      alert("Error al enviar feedback. Intenta de nuevo.");
    },
  });

  const items = queue?.items ?? [];
  const pendingItems = items.filter((it) => !dismissed.has(it.expediente));
  const queueSize = queue?.total ?? items.length;

  // Group by technology if available
  const techCounts: Record<string, number> = {};
  for (const item of items) {
    if (item.tecnologia) {
      techCounts[item.tecnologia] = (techCounts[item.tecnologia] ?? 0) + 1;
    }
  }
  const hasTechData = Object.keys(techCounts).length > 0;

  const handleLabel = (expediente: string, relevante: boolean) => {
    submitFeedback.mutate({
      expediente,
      relevante,
      nota: notes[expediente],
    });
  };

  const handleSkip = (expediente: string) => {
    setDismissed((prev) => new Set(prev).add(expediente));
  };

  const toggleNote = (expediente: string) => {
    setExpandedNotes((prev) => {
      const next = new Set(prev);
      if (next.has(expediente)) next.delete(expediente);
      else next.add(expediente);
      return next;
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Active Learning</h1>
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
            (uncertainty sampling).
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
              className="h-full bg-primary rounded-full transition-all"
              style={{
                width: `${Math.min((dismissed.size / items.length) * 100, 100)}%`,
              }}
            />
          </div>
        )}
      </div>

      {/* Labeling queue */}
      <h2 className="text-xl font-semibold">Cola de etiquetado</h2>

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
            const prob = item.proba ?? item.probability ?? null;
            const noteExpanded = expandedNotes.has(item.expediente);

            return (
              <Card key={item.expediente}>
                <CardContent className="pt-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 flex-1 space-y-2">
                      <p className="font-medium leading-snug">
                        {item.titulo ?? "Sin titulo"}
                      </p>
                      <p className="text-xs text-muted-foreground font-mono">
                        {item.expediente}
                      </p>
                      {prob != null && (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground">
                            Probabilidad:
                          </span>
                          <div className="flex-1 h-2 max-w-[200px] rounded-full bg-muted overflow-hidden">
                            <div
                              className={cn(
                                "h-full rounded-full transition-all",
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
                      {item.tecnologia && (
                        <Badge variant="outline" className="text-xs">
                          {item.tecnologia}
                        </Badge>
                      )}
                    </div>
                    <div className="flex flex-col gap-2 shrink-0">
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          className="bg-green-600 hover:bg-green-700"
                          onClick={() => handleLabel(item.expediente, true)}
                          disabled={submitFeedback.isPending}
                        >
                          <ThumbsUp className="mr-1 h-4 w-4" />
                          Relevante
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleLabel(item.expediente, false)}
                          disabled={submitFeedback.isPending}
                        >
                          <ThumbsDown className="mr-1 h-4 w-4" />
                          No relevante
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleSkip(item.expediente)}
                        >
                          <SkipForward className="mr-1 h-4 w-4" />
                          Saltar
                        </Button>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-xs"
                        onClick={() => toggleNote(item.expediente)}
                      >
                        {noteExpanded ? (
                          <ChevronUp className="mr-1 h-3 w-3" />
                        ) : (
                          <ChevronDown className="mr-1 h-3 w-3" />
                        )}
                        Nota
                      </Button>
                    </div>
                  </div>
                  {noteExpanded && (
                    <Textarea
                      className="mt-2 w-full"
                      placeholder="Nota opcional..."
                      rows={2}
                      value={notes[item.expediente] ?? ""}
                      onChange={(e) =>
                        setNotes((prev) => ({
                          ...prev,
                          [item.expediente]: e.target.value,
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
