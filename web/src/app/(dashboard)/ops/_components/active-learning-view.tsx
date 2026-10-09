"use client";

/**
 * Etiquetado (active learning) — cola de etiquetado; por defecto, por
 * desacuerdo entre reglas, LLM y modelo.
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
        <h1 className="sr-only">Etiquetado</h1>
        <p className="text-tf-meta text-muted-foreground">
          Revisión humana de si cada licitación es TI y de qué familia.
        </p>
      </div>

      <Aviso tone="info" role="note">
        Por defecto la cola pone delante las licitaciones en las que reglas, LLM y modelo no coinciden
        (desacuerdo) y después las etiquetas heredadas que decían «es SAP», cada una con su motivo y la propuesta
        del LLM, que se acepta de un clic; también puedes muestrear por incertidumbre del modelo o al azar. Para
        etiquetar a mano, marca familias y fabricantes en la lista de la tarjeta, que arranca con la propuesta del
        LLM: la primera que marques es la principal. En la predicción del modelo, pulsar una tecnología la hace
        principal; con Mayús pulsada, la añade o la quita.
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
        ultimaRegistrada={estado.ultimaRegistrada}
      />

      {estado.hasTechData && <TechQueueChips techCounts={estado.techCounts} />}

      <LabelingQueue estado={estado} />
    </div>
  );
}
