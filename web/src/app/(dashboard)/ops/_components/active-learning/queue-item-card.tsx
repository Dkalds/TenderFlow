"use client";

/** Una tarjeta de la cola: qué es el expediente, qué cree el modelo y qué decide la persona. */

import { ChevronDown, ChevronUp } from "lucide-react";
import { Panel } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { ModelVersionInfo, QueueItem } from "../../_hooks/use-active-learning";
import { ModelPrediction } from "./model-prediction";
import { QueueItemHeader } from "./queue-item-header";

export function QueueItemCard({
  item,
  activeModel,
  chosenTech,
  chosenSecs,
  note,
  noteExpanded,
  descExpanded,
  isSubmitting,
  onSelectTech,
  onClearSelection,
  onToggleNote,
  onToggleDesc,
  onNoteChange,
  onConfirm,
  onNotRelevant,
  onSkip,
}: {
  item: QueueItem;
  activeModel: ModelVersionInfo | null;
  chosenTech: string | null;
  chosenSecs: Set<string>;
  note: string;
  noteExpanded: boolean;
  descExpanded: boolean;
  isSubmitting: boolean;
  onSelectTech: (tech: string, shiftKey: boolean) => void;
  onClearSelection: () => void;
  onToggleNote: () => void;
  onToggleDesc: () => void;
  onNoteChange: (value: string) => void;
  onConfirm: () => void;
  onNotRelevant: () => void;
  onSkip: () => void;
}) {
  const hasSelection = chosenTech != null;
  const idNota = `nota-${item.id_externo}`;

  return (
    <Panel className="space-y-3">
      <QueueItemHeader item={item} descExpanded={descExpanded} onToggleDesc={onToggleDesc} />

      <ModelPrediction
        item={item}
        activeModel={activeModel}
        chosenTech={chosenTech}
        chosenSecs={chosenSecs}
        onSelectTech={onSelectTech}
      />

      {/* Acciones */}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <Tooltip>
          {/* El botón se deshabilita sin selección, y deshabilitado
              no emite eventos de puntero: el disparador tiene que
              ser el `span`, que es justo cuando el tooltip explica
              por qué no se puede pulsar. */}
          <TooltipTrigger asChild>
            <span className="inline-flex">
              <Button size="sm" onClick={onConfirm} disabled={isSubmitting || !hasSelection}>
                {hasSelection ? `Confirmar: ${chosenTech}` : "Confirmar etiqueta"}
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent>
            {hasSelection
              ? `Confirmar: ${chosenTech}${chosenSecs.size ? ` + ${Array.from(chosenSecs).join(", ")}` : ""}`
              : "Selecciona una tecnología primero"}
          </TooltipContent>
        </Tooltip>
        <Button size="sm" variant="outline" onClick={onNotRelevant} disabled={isSubmitting}>
          Ninguna / no relevante
        </Button>
        <Button size="sm" variant="ghost" onClick={onSkip}>
          Saltar
        </Button>
        {chosenTech && (
          <Button size="sm" variant="ghost" onClick={onClearSelection}>
            Limpiar selección
          </Button>
        )}
      </div>

      {/* Nota */}
      <Button
        variant="ghost"
        size="sm"
        onClick={onToggleNote}
        aria-expanded={noteExpanded}
        aria-controls={noteExpanded ? idNota : undefined}
      >
        Nota
        {noteExpanded ? <ChevronUp aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
      </Button>
      {noteExpanded && (
        <Textarea
          id={idNota}
          aria-label="Nota sobre esta licitación"
          className="mt-2 w-full"
          placeholder="Nota opcional…"
          rows={2}
          value={note}
          onChange={(e) => onNoteChange(e.target.value)}
        />
      )}
    </Panel>
  );
}
