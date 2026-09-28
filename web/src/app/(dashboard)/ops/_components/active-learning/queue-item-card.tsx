"use client";

/** Una tarjeta de la cola: qué es el expediente, qué cree el modelo y qué decide la persona. */

import { ChevronDown, ChevronUp } from "lucide-react";
import { Panel } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatPercent } from "@/lib/utils";
import type { EtiquetaTaxonomia, LlmProposal, ModelVersionInfo, QueueItem } from "../../_lib/active-learning";
import { ModelPrediction } from "./model-prediction";
import { QueueItemHeader } from "./queue-item-header";
import { SelectorTaxonomia } from "./selector-taxonomia";

/** Por qué está un expediente en la cola por desacuerdo (`db/repositories/revision_ti.py`). */
const MOTIVO_LEGIBLE: Record<string, string> = {
  llm_no_reglas_si: "El LLM dice que no es TI; las reglas, que sí",
  llm_si_reglas_no: "El LLM dice que es TI; ni las reglas ni el CPV lo ven",
  llm_no_cpv_si: "El CPV es de informática; el LLM dice que no es TI",
  familias_distintas: "El LLM y las reglas ven familias distintas",
  legado: "Etiqueta heredada: decía «es SAP», hay que revisarla como «es TI»",
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
    return <p className="text-tf-meta text-muted-foreground">{`Familias del LLM: ${llm.familias.join(", ")}`}</p>;
  }

  const propuesta = llm.es_ti
    ? ["es TI", ...(llm.familias.length > 0 ? [llm.familias.join(", ")] : [])].join(" · ")
    : "no es TI";

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2">
      <p className="text-tf-body">
        <span className="font-medium">{`Propuesta del LLM: ${propuesta}`}</span>
        {llm.confianza_es_ti != null && (
          <span className="ml-1 text-muted-foreground">
            {`(${formatPercent(llm.confianza_es_ti * 100, 0)} de confianza)`}
          </span>
        )}
      </p>
      {llm.sin_evidencia ? (
        // Afirmó familias sin cita que se sostenga: esa respuesta no entrena,
        // así que aceptarla de un clic guardaría una etiqueta que el LLM no
        // respaldó. Se decide con el formulario de abajo.
        <p className="w-full text-tf-meta text-muted-foreground">
          Sin «Aceptar»: el LLM nombró familias sin una cita del anuncio que las sostenga.
        </p>
      ) : (
        <Button size="sm" variant="secondary" className="ml-auto" onClick={onAccept} disabled={isSubmitting}>
          Aceptar propuesta
        </Button>
      )}
    </div>
  );
}

export function QueueItemCard({
  item,
  activeModel,
  taxonomia,
  seleccion,
  note,
  noteExpanded,
  descExpanded,
  isSubmitting,
  onSelectTech,
  onToggleTech,
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
  /** La taxonomía entera que ofrece el selector (`GET /feedback/taxonomia`). */
  taxonomia: EtiquetaTaxonomia[];
  /** Familias y fabricantes marcados: el primero es la principal. */
  seleccion: string[];
  note: string;
  noteExpanded: boolean;
  descExpanded: boolean;
  isSubmitting: boolean;
  onSelectTech: (tech: string, shiftKey: boolean) => void;
  onToggleTech: (codigo: string) => void;
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
  const [principal, ...secundarias] = seleccion;
  const hasSelection = principal != null;
  const nombre = (codigo: string) => taxonomia.find((etiqueta) => etiqueta.codigo === codigo)?.etiqueta ?? codigo;
  const idNota = `nota-${item.id_externo}`;

  return (
    <Panel className="space-y-3">
      <QueueItemHeader item={item} descExpanded={descExpanded} onToggleDesc={onToggleDesc} />

      {item.motivo && (
        <div>
          <Badge variant="warning">{MOTIVO_LEGIBLE[item.motivo] ?? item.motivo}</Badge>
        </div>
      )}

      {item.llm && <PropuestaLlm llm={item.llm} isSubmitting={isSubmitting} onAccept={onAcceptLlm} />}

      <ModelPrediction
        item={item}
        activeModel={activeModel}
        chosenTech={principal ?? null}
        chosenSecs={new Set(secundarias)}
        onSelectTech={onSelectTech}
      />

      <SelectorTaxonomia taxonomia={taxonomia} seleccion={seleccion} onToggle={onToggleTech} />

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
                {hasSelection ? `Es TI: ${nombre(principal)}` : "Es TI: elige familia"}
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent>
            {hasSelection
              ? `Es TI: ${nombre(principal)}${secundarias.length ? ` + ${secundarias.map(nombre).join(", ")}` : ""}`
              : "Marca al menos una familia o un fabricante"}
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex">
              <Button size="sm" variant="outline" onClick={onTiWithoutFamily} disabled={isSubmitting}>
                Es TI, sin familia
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent>Es un contrato de TI, pero de ninguna familia de la lista</TooltipContent>
        </Tooltip>
        <Button size="sm" variant="outline" onClick={onNotRelevant} disabled={isSubmitting}>
          No es TI
        </Button>
        <Button size="sm" variant="ghost" onClick={onSkip}>
          Saltar
        </Button>
        {hasSelection && (
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
