"use client";

/**
 * La cola en sí: progreso de la sesión, selector de estrategia y las tarjetas
 * pendientes con sus cuatro estados (error, carga, vacía, lista).
 *
 * Recibe el estado completo del hook y no el desglose en veinte props: cada
 * tarjeta necesita su rebanada de la selección por expediente, y trocearlo aquí
 * solo desplazaría el mismo acoplamiento a la firma.
 */

import { Activity } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import type { ActiveLearning } from "../../_hooks/use-active-learning";
import { QueueItemCard } from "./queue-item-card";

export function TechQueueChips({ techCounts }: { techCounts: Record<string, number> }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Tecnologías en cola</CardTitle>
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
  );
}

export function LabelingQueue({ estado }: { estado: ActiveLearning }) {
  const { items, pendingItems, queueLoading, queueError, dismissedCount, strategy } = estado;

  return (
    <>
      <Separator />

      {/* Progress */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Activity className="h-4 w-4" />
        <span>
          {dismissedCount} de {items.length} ítems revisados en esta sesión
        </span>
        {items.length > 0 && (
          <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden max-w-xs">
            <div
              className="h-full bg-primary rounded-full transition-[width]"
              style={{
                width: `${Math.min((dismissedCount / items.length) * 100, 100)}%`,
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
            onClick={() => estado.setStrategy("uncertainty")}
          >
            Incertidumbre
          </Button>
          <Button
            size="sm"
            variant={strategy === "random" ? "default" : "outline"}
            onClick={() => estado.setStrategy("random")}
          >
            Aleatoria
          </Button>
        </div>
      </div>

      {queueError && (
        <Card className="border-destructive">
          <CardContent className="pt-6 text-destructive">
            Error al cargar cola de feedback. Verifica que la API esté activa.
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
                ? "No hay ítems en la cola de feedback"
                : "Has revisado todos los ítems de esta sesión"}
            </p>
          </CardContent>
        </Card>
      )}

      {!queueLoading && (
        <div className="space-y-3">
          {pendingItems.map((item) => (
            <QueueItemCard
              key={item.id_externo}
              item={item}
              activeModel={estado.activeModel}
              chosenTech={estado.selectedTech[item.id_externo] ?? null}
              chosenSecs={estado.secondaryTechs[item.id_externo] ?? new Set<string>()}
              note={estado.notes[item.id_externo] ?? ""}
              noteExpanded={estado.expandedNotes.has(item.id_externo)}
              descExpanded={estado.expandedDesc.has(item.id_externo)}
              isSubmitting={estado.isSubmitting}
              onSelectTech={(tech, shiftKey) => estado.selectTech(item.id_externo, tech, shiftKey)}
              onClearSelection={() => estado.clearSelection(item.id_externo)}
              onToggleNote={() => estado.toggleNote(item.id_externo)}
              onToggleDesc={() => estado.toggleDesc(item.id_externo)}
              onNoteChange={(value) => estado.setNote(item.id_externo, value)}
              onConfirm={() => estado.confirmLabel(item.id_externo)}
              onNotRelevant={() => estado.markNotRelevant(item.id_externo)}
              onSkip={() => estado.skip(item.id_externo)}
            />
          ))}
        </div>
      )}
    </>
  );
}
