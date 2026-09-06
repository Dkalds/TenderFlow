"use client";

/**
 * Active learning — cola de etiquetado de las muestras con más incertidumbre.
 *
 * Vista compartida por la ruta `/active-learning` y por `?vista=etiquetado` del
 * espacio Ops. La guarda de administrador viaja con la vista (ver la nota en
 * `administracion-view.tsx`).
 *
 * El estado y las llamadas viven en `_hooks/use-active-learning.ts`; los
 * bloques de pantalla, en `_components/active-learning/`. Aquí queda el orden
 * de la página y nada más.
 */

import { Info } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { AdminGuard } from "@/components/admin-guard";
import { useActiveLearning } from "../_hooks/use-active-learning";
import { LabelingStats } from "./active-learning/labeling-stats";
import { LabelingQueue, TechQueueChips } from "./active-learning/labeling-queue";
import { ModelInfoCard } from "./active-learning/model-info-card";

export default function ActiveLearningView() {
  return (
    <AdminGuard>
      <ActiveLearningContent />
    </AdminGuard>
  );
}

function ActiveLearningContent() {
  const estado = useActiveLearning();

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
            modelo ML para mejorar la precisión del clasificador. Las
            oportunidades se seleccionan mediante muestreo por incertidumbre
            (uncertainty sampling). Selecciona la tecnología principal haciendo
            click en el chip; usa shift-click para marcar tecnologías
            secundarias.
          </span>
        </CardContent>
      </Card>

      <LabelingStats
        stats={estado.stats}
        statsLoading={estado.statsLoading}
        queueSize={estado.queueSize}
        queueLoading={estado.queueLoading}
      />

      <ModelInfoCard
        stats={estado.stats}
        activeModel={estado.activeModel}
        metric={estado.metric}
        metricTrend={estado.metricTrend}
        feedbacksSinceTrain={estado.feedbacksSinceTrain}
      />

      {estado.hasTechData && <TechQueueChips techCounts={estado.techCounts} />}

      <LabelingQueue estado={estado} />
    </div>
  );
}
