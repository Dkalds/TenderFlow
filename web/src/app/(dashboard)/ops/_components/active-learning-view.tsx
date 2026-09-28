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

import { Aviso } from "@/components/console/panel";
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
        <h1 className="sr-only">Active learning</h1>
        <p className="text-tf-meta text-muted-foreground">
          Etiquetado de las licitaciones en las que el clasificador duda más.
        </p>
      </div>

      <Aviso tone="info" role="note">
        Al etiquetar a mano las licitaciones en la zona de duda del modelo (muestreo por incertidumbre), el
        clasificador aprende más rápido. Pulsa una tecnología de la predicción para marcarla como principal; con
        Mayús pulsada, como secundaria.
      </Aviso>

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
