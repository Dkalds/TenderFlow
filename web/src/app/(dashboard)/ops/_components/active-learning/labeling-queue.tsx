"use client";

/**
 * La cola en sí: progreso de la sesión, selector de estrategia y las tarjetas
 * pendientes con sus cuatro estados (error, carga, vacía, lista).
 *
 * Recibe el estado completo del hook y no el desglose en veinte props: cada
 * tarjeta necesita su rebanada de la selección por expediente, y trocearlo aquí
 * solo desplazaría el mismo acoplamiento a la firma.
 */

import { Panel, PanelEmpty, PanelError, PanelTitle, Segmented } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import type { ActiveLearning } from "../../_hooks/use-active-learning";
import type { Strategy } from "../../_lib/active-learning";
import { QueueItemCard } from "./queue-item-card";

const ESTRATEGIAS: { value: Strategy; label: string }[] = [
  { value: "desacuerdo", label: "Desacuerdo" },
  { value: "uncertainty", label: "Incertidumbre" },
  { value: "random", label: "Aleatoria" },
];

export function TechQueueChips({ techCounts }: { techCounts: Record<string, number> }) {
  return (
    <Panel>
      <PanelTitle title="Tecnologías en cola" />
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(techCounts).map(([tech, count]) => (
          <Badge key={tech} variant="outline">
            {tech}: <span className="tf-tnum">{count}</span>
          </Badge>
        ))}
      </div>
    </Panel>
  );
}

export function LabelingQueue({ estado }: { estado: ActiveLearning }) {
  const { items, pendingItems, queueLoading, queueError, dismissedCount, strategy } = estado;

  return (
    <>
      <Separator />

      {/* Progreso de la sesión */}
      <div className="flex items-center gap-3 text-tf-meta text-muted-foreground">
        <span>
          {dismissedCount} de {items.length} revisadas en esta sesión
        </span>
        {items.length > 0 && (
          <div className="h-1.5 max-w-xs flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-[width]"
              style={{
                width: `${Math.min((dismissedCount / items.length) * 100, 100)}%`,
              }}
            />
          </div>
        )}
      </div>

      {/* Cola de etiquetado */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-tf-body font-semibold">Cola de etiquetado</h2>
        <div className="flex items-center gap-2">
          <span className="text-tf-meta text-muted-foreground">Estrategia</span>
          <Segmented
            aria-label="Estrategia de muestreo"
            value={strategy}
            options={ESTRATEGIAS}
            onChange={estado.setStrategy}
          />
        </div>
      </div>

      {queueError != null && (
        <PanelError title="No se pudo cargar la cola de etiquetado" error={queueError} onRetry={estado.retryQueue} />
      )}

      {queueLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28 w-full rounded-xl" />
          ))}
        </div>
      )}

      {!queueLoading && queueError == null && pendingItems.length === 0 && (
        <PanelEmpty
          title={
            items.length === 0 ? "No hay licitaciones en la cola" : "Has revisado toda la cola de esta sesión"
          }
          hint={
            items.length === 0
              ? "Cuando reglas, LLM y modelo no coincidan en alguna licitación, o el modelo dude de ella, aparecerá aquí para que la etiquetes."
              : "Cambia de estrategia o vuelve más tarde para ver más."
          }
        />
      )}

      {!queueLoading && (
        <div className="space-y-3">
          {pendingItems.map((item) => (
            <QueueItemCard
              key={item.id_externo}
              item={item}
              activeModel={estado.activeModel}
              taxonomia={estado.taxonomia}
              seleccion={estado.seleccionDe(item.id_externo)}
              note={estado.notes[item.id_externo] ?? ""}
              noteExpanded={estado.expandedNotes.has(item.id_externo)}
              descExpanded={estado.expandedDesc.has(item.id_externo)}
              isSubmitting={estado.isSubmitting}
              onSelectTech={(tech, shiftKey) => estado.selectTech(item.id_externo, tech, shiftKey)}
              onToggleTech={(codigo) => estado.toggleTech(item.id_externo, codigo)}
              onClearSelection={() => estado.clearSelection(item.id_externo)}
              onToggleNote={() => estado.toggleNote(item.id_externo)}
              onToggleDesc={() => estado.toggleDesc(item.id_externo)}
              onNoteChange={(value) => estado.setNote(item.id_externo, value)}
              onConfirm={() => estado.confirmLabel(item.id_externo)}
              onNotRelevant={() => estado.markNotRelevant(item.id_externo)}
              onAcceptLlm={() => estado.acceptLlmProposal(item.id_externo)}
              onTiWithoutFamily={() => estado.markTiWithoutFamily(item.id_externo)}
              onSkip={() => estado.skip(item.id_externo)}
            />
          ))}
        </div>
      )}
    </>
  );
}
