"use client";

/** Una tarjeta de la cola: qué es el expediente, qué cree el modelo y qué decide la persona. */

import {
  Bot,
  Check,
  ChevronDown,
  ChevronUp,
  SkipForward,
  ThumbsDown,
  ThumbsUp,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatPercent } from "@/lib/utils";
import type { LlmProposal, ModelVersionInfo, QueueItem } from "../../_lib/active-learning";
import { ModelPrediction } from "./model-prediction";
import { QueueItemHeader } from "./queue-item-header";

/** Por qué está un expediente en la cola por desacuerdo (`db/repositories/revision_ti.py`). */
const MOTIVO_LEGIBLE: Record<string, string> = {
  llm_no_reglas_si: "El LLM dice que no es TI; las reglas, que sí",
  llm_si_reglas_no: "El LLM dice que es TI; ni las reglas ni el CPV lo ven",
  llm_no_cpv_si: "El CPV es de informática; el LLM dice que no es TI",
  familias_distintas: "El LLM y las reglas ven familias distintas",
  modelo_dudoso: "El modelo no está seguro",
};

function PropuestaLlm({
  llm,
  isSubmitting,
  onAccept,
}: {
  llm: LlmProposal;
  isSubmitting: boolean;
  onAccept: () => void;
}) {
  if (llm.es_ti == null) {
    // Respuestas anteriores al prompt v3: traen familias pero no el marcador
    // de es_ti, así que no hay `relevante` que aceptar de un clic.
    if (llm.familias.length === 0) return null;
    return (
      <p className="text-sm text-muted-foreground">
        {`Familias del LLM: ${llm.familias.join(", ")}`}
      </p>
    );
  }

  const propuesta = llm.es_ti
    ? ["es TI", ...(llm.familias.length > 0 ? [llm.familias.join(", ")] : [])].join(" · ")
    : "no es TI";

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2">
      <Bot className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <p className="text-sm">
        <span className="font-medium">{`Propuesta del LLM: ${propuesta}`}</span>
        {llm.confianza_es_ti != null && (
          <span className="ml-1 text-muted-foreground">
            {`(${formatPercent(llm.confianza_es_ti * 100, 0)} de confianza)`}
          </span>
        )}
      </p>
      <Button
        size="sm"
        variant="secondary"
        className="ml-auto"
        onClick={onAccept}
        disabled={isSubmitting}
      >
        <Check className="mr-1 h-4 w-4" aria-hidden="true" />
        Aceptar propuesta
      </Button>
    </div>
  );
}

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
  onAcceptLlm,
  onTiWithoutFamily,
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
  onAcceptLlm: () => void;
  onTiWithoutFamily: () => void;
  onSkip: () => void;
}) {
  const hasSelection = chosenTech != null;

  return (
    <Card>
      <CardContent className="pt-4 space-y-3">
        <QueueItemHeader item={item} descExpanded={descExpanded} onToggleDesc={onToggleDesc} />

        {item.motivo && (
          <div>
            <Badge variant="warning" className="text-xs">
              {MOTIVO_LEGIBLE[item.motivo] ?? item.motivo}
            </Badge>
          </div>
        )}

        {item.llm && (
          <PropuestaLlm llm={item.llm} isSubmitting={isSubmitting} onAccept={onAcceptLlm} />
        )}

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
                  {hasSelection ? `Es TI: ${chosenTech}` : "Es TI: elige familia"}
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>
              {hasSelection
                ? `Es TI: ${chosenTech}${
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
                  variant="outline"
                  onClick={onTiWithoutFamily}
                  disabled={isSubmitting}
                >
                  <ThumbsUp className="mr-1 h-4 w-4" aria-hidden="true" />
                  Es TI, sin familia
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>Es un contrato de TI, pero de ninguna familia de la lista</TooltipContent>
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
                  No es TI
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>No es un contrato de TI</TooltipContent>
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
