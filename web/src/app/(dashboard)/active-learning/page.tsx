"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
import { BrainCircuit, Check, X, SkipForward, Info } from "lucide-react";
import { formatCurrency, formatNumber } from "@/lib/utils";

interface ScoringItem {
  id?: string;
  expediente?: string;
  titulo?: string;
  organo?: string;
  importe?: number;
  score?: number;
  band?: string;
}

interface ScoringResponse {
  items?: ScoringItem[];
  results?: ScoringItem[];
  bands?: Record<string, number>;
  total?: number;
}

export default function ActiveLearningPage() {
  const [labeled, setLabeled] = useState<Set<string>>(new Set());
  const [sessionCount, setSessionCount] = useState(0);

  const { data, isLoading, isError } = useQuery<ScoringResponse>({
    queryKey: ["scoring-uncertainty"],
    queryFn: async () => {
      const res = await fetch("/api/v1/analytics/scoring?min_score=30&band=media", {
        credentials: "include",
      });
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.json();
    },
  });

  const items = data?.items ?? data?.results ?? [];
  const totalItems = items.length;
  const pendingItems = items.filter((it) => !labeled.has(it.id ?? it.expediente ?? ""));

  const handleAction = (id: string, _action: "confirm" | "reject" | "skip") => {
    setLabeled((prev) => new Set(prev).add(id));
    if (_action !== "skip") {
      setSessionCount((c) => c + 1);
    }
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
            Etiquetado humano de licitaciones en la zona de incertidumbre del modelo ML
            para mejorar la precision del clasificador. Las oportunidades mostradas tienen
            scores entre 40-60, donde el modelo tiene menor confianza.
          </span>
        </CardContent>
      </Card>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="pt-6 text-center">
            <p className="text-2xl font-bold">
              {isLoading ? <Skeleton className="h-8 w-16 mx-auto" /> : formatNumber(totalItems)}
            </p>
            <p className="text-sm text-muted-foreground">Items en zona de incertidumbre</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6 text-center">
            <p className="text-2xl font-bold">{sessionCount}</p>
            <p className="text-sm text-muted-foreground">Etiquetados esta sesion</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6 text-center">
            <p className="text-2xl font-bold">{pendingItems.length}</p>
            <p className="text-sm text-muted-foreground">Pendientes</p>
          </CardContent>
        </Card>
      </div>

      {/* Band distribution from scoring if available */}
      {data?.bands && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Distribucion por banda de score</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-3">
              {Object.entries(data.bands).map(([band, count]) => (
                <Badge key={band} variant="outline" className="text-sm py-1 px-3">
                  {band}: {formatNumber(count as number)}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Separator />

      {/* Progress */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <BrainCircuit className="h-4 w-4" />
        <span>
          {sessionCount} de {totalItems} items etiquetados en esta sesion
        </span>
        {totalItems > 0 && (
          <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden max-w-xs">
            <div
              className="h-full bg-primary rounded-full transition-all"
              style={{ width: `${Math.min((sessionCount / totalItems) * 100, 100)}%` }}
            />
          </div>
        )}
      </div>

      {/* Labeling queue */}
      <h2 className="text-xl font-semibold">Cola de etiquetado</h2>

      {isError && (
        <Card className="border-destructive">
          <CardContent className="pt-6 text-destructive">
            Error al cargar datos de scoring. Verifica que la API este activa.
          </CardContent>
        </Card>
      )}

      {isLoading && (
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

      {!isLoading && pendingItems.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="py-12 text-center">
            <BrainCircuit className="h-12 w-12 text-muted-foreground/50 mx-auto mb-4" />
            <p className="text-lg font-medium text-muted-foreground">
              {totalItems === 0
                ? "No hay items en la zona de incertidumbre"
                : "Has revisado todos los items de esta sesion"}
            </p>
          </CardContent>
        </Card>
      )}

      {!isLoading && (
        <div className="space-y-3">
          {pendingItems.map((item) => {
            const itemId = item.id ?? item.expediente ?? "";
            return (
              <Card key={itemId}>
                <CardContent className="pt-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="font-medium leading-snug">
                        {item.titulo ?? "Sin titulo"}
                      </p>
                      {item.organo && (
                        <p className="text-sm text-muted-foreground">{item.organo}</p>
                      )}
                      <div className="flex flex-wrap gap-2">
                        {item.importe != null && (
                          <Badge variant="secondary">
                            {formatCurrency(item.importe)}
                          </Badge>
                        )}
                        {item.score != null && (
                          <Badge variant="outline">Score: {item.score}</Badge>
                        )}
                        {item.band && (
                          <Badge variant="outline">Banda: {item.band}</Badge>
                        )}
                      </div>
                    </div>
                    <div className="flex gap-2 shrink-0">
                      <Button
                        size="sm"
                        variant="default"
                        onClick={() => handleAction(itemId, "confirm")}
                      >
                        <Check className="mr-1 h-4 w-4" />
                        Confirmar
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => handleAction(itemId, "reject")}
                      >
                        <X className="mr-1 h-4 w-4" />
                        Rechazar
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleAction(itemId, "skip")}
                      >
                        <SkipForward className="mr-1 h-4 w-4" />
                        Saltar
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
