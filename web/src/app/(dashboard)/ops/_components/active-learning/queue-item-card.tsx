"use client";

/** Una tarjeta de la cola: qué es el expediente, qué cree el modelo y qué decide la persona. */

import { ChevronDown, ChevronUp, SkipForward, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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

  return (
    <Card>
      <CardContent className="pt-4 space-y-3">
        <QueueItemHeader item={item} descExpanded={descExpanded} onToggleDesc={onToggleDesc} />

        <ModelPrediction
          item={item}
          activeModel={activeModel}
          chosenTech={chosenTech}
          chosenSecs={chosenSecs}
          onSelectTech={onSelectTech}
        />

        {/* Action buttons */}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Tooltip>
            {/* El botón se deshabilita sin selección, y deshabilitado
                no emite eventos de puntero: el disparador tiene que
                ser el `span`, que es justo cuando el tooltip explica
                por qué no se puede pulsar. */}
            <TooltipTrigger asChild>
              <span className="inline-flex">
                <Button
                  size="sm"
                  className="bg-green-600 hover:bg-green-700"
                  onClick={onConfirm}
                  disabled={isSubmitting || !hasSelection}
                >
                  <ThumbsUp className="mr-1 h-4 w-4" aria-hidden="true" />
                  {hasSelection
                    ? `Confirmar: ${chosenTech}`
                    : "Confirmar etiqueta"}
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>
              {hasSelection
                ? `Confirmar: ${chosenTech}${
                    chosenSecs.size
                      ? ` + ${Array.from(chosenSecs).join(", ")}`
                      : ""
                  }`
                : "Selecciona una tecnología primero"}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="inline-flex">
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={onNotRelevant}
                  disabled={isSubmitting}
                >
                  <ThumbsDown className="mr-1 h-4 w-4" aria-hidden="true" />
                  Ninguna / no relevante
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>Ninguna tecnología / no relevante</TooltipContent>
          </Tooltip>
          <Button size="sm" variant="ghost" onClick={onSkip}>
            <SkipForward className="mr-1 h-4 w-4" />
            Saltar
          </Button>
          {chosenTech && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-xs"
                  onClick={onClearSelection}
                >
                  <X className="mr-1 h-3 w-3" aria-hidden="true" />
                  Limpiar
                </Button>
              </TooltipTrigger>
              <TooltipContent>Limpiar selección</TooltipContent>
            </Tooltip>
          )}
        </div>

        {/* Note toggle */}
        <Button variant="ghost" size="sm" className="text-xs" onClick={onToggleNote}>
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
            placeholder="Nota opcional…"
            rows={2}
            value={note}
            onChange={(e) => onNoteChange(e.target.value)}
          />
        )}
      </CardContent>
    </Card>
  );
}
