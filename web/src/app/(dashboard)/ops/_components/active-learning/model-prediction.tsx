"use client";

/**
 * Lo que el modelo cree de un expediente: la confianza binaria heredada del
 * clasificador SAP y, si el ítem trae `model`, una fila por familia con su
 * score, su umbral y el estado de la selección humana.
 */

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn, formatDate } from "@/lib/utils";
import type { ModelVersionInfo, QueueItem, TechModel } from "../../_hooks/use-active-learning";

function ConfianzaBinaria({ prob }: { prob: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-tf-meta text-muted-foreground">
        Confianza SAP (sí/no):
      </span>
      <div className="flex-1 h-1.5 max-w-[200px] rounded-full bg-muted overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full",
            prob >= 0.7
              ? "bg-success"
              : prob >= 0.4
                ? "bg-warning"
                : "bg-destructive",
          )}
          style={{
            width: `${Math.min(prob * 100, 100)}%`,
          }}
        />
      </div>
      <span className="tf-tnum text-tf-meta font-medium">
        {(prob * 100).toFixed(1)}%
      </span>
    </div>
  );
}

function TechScoreRow({
  tech,
  score,
  model,
  isSelected,
  isSecondary,
  onSelect,
}: {
  tech: string;
  score: number;
  model: TechModel;
  isSelected: boolean;
  isSecondary: boolean;
  onSelect: (shiftKey: boolean) => void;
}) {
  const threshold = model.tech_thresholds[tech] ?? 0.5;
  const isPredicted = model.tech_predicted.includes(tech);
  const isPrincipal = model.tech_principal === tech;

  return (
    <button
      type="button"
      onClick={(e) => onSelect(e.shiftKey)}
      className={cn(
        "w-full flex items-center gap-2 px-2 py-1 rounded-md text-tf-body transition-colors",
        "hover:bg-muted/70 focus:outline-none focus:ring-1 focus:ring-ring",
        isSelected && "ring-2 ring-primary bg-primary/5",
        isSecondary && !isSelected && "ring-1 ring-info/60 bg-info/5",
      )}
      /* Aquí no va `Tooltip`: son ~12 filas de score por
         cada uno de los 20 items de la cola, o sea ~240
         Popovers de Radix montados de golpe. El texto
         que llevaba el `title` era además redundante con
         lo que ya se ve (barra, %, color, ●/○); como
         `aria-label` deja de ser sólo-ratón y encima
         expone a lectores de pantalla el estado que
         hasta ahora sólo estaba en el color. */
      aria-label={`${tech} — Score: ${(score * 100).toFixed(1)}%, umbral ${(threshold * 100).toFixed(0)}%${
        isPrincipal ? " (principal)" : ""
      }${isSelected ? " [seleccionada]" : ""}${
        isSecondary ? " [secundaria]" : ""
      }`}
    >
      <span
        className={cn(
          "w-[72px] shrink-0 text-tf-meta font-mono font-medium text-left",
          isPrincipal && "text-success",
          isSelected && "text-primary font-semibold",
          isSecondary && !isSelected && "text-info",
        )}
      >
        {tech}
      </span>
      <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full",
            isSelected
              ? "bg-primary"
              : isSecondary
                ? "bg-info"
                : score >= threshold
                  ? "bg-success"
                  : "bg-muted-foreground/30",
          )}
          style={{
            width: `${Math.min(score * 100, 100)}%`,
          }}
        />
        {threshold > 0 && threshold < 1 && (
          <div
            aria-hidden="true"
            className="absolute top-0 h-full w-px bg-destructive/60"
            style={{
              left: `${threshold * 100}%`,
              height: "8px",
              position: "relative",
              marginTop: "-8px",
            }}
          />
        )}
      </div>
      <span className="tf-tnum text-tf-meta w-[42px] text-right shrink-0">
        {(score * 100).toFixed(0)}%
      </span>
      {isPredicted && !isSelected && !isSecondary && (
        <span
          aria-hidden="true"
          className="text-tf-micro text-success shrink-0"
        >
          ✓
        </span>
      )}
      {isSelected && (
        <span aria-hidden="true" className="text-tf-micro text-primary shrink-0 font-bold">
          ●
        </span>
      )}
      {isSecondary && !isSelected && (
        <span aria-hidden="true" className="text-tf-micro text-info shrink-0 font-bold">
          ○
        </span>
      )}
    </button>
  );
}

export function ModelPrediction({
  item,
  activeModel,
  chosenTech,
  chosenSecs,
  onSelectTech,
}: {
  item: QueueItem;
  activeModel: ModelVersionInfo | null;
  chosenTech: string | null;
  chosenSecs: Set<string>;
  onSelectTech: (tech: string, shiftKey: boolean) => void;
}) {
  const prob = item.confidence ?? null;
  const model = item.model;
  const sortedScores = model
    ? Object.entries(model.tech_scores).sort(([, a], [, b]) => b - a)
    : [];

  return (
    <>
      {prob != null && <ConfianzaBinaria prob={prob} />}

      {model && sortedScores.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-tf-meta font-medium text-muted-foreground">
              Predicción del modelo
            </span>
            {activeModel && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="font-mono text-tf-meta text-muted-foreground">
                    (v{activeModel.version})
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  {`Modelo v${activeModel.version}${
                    activeModel.trained_at
                      ? ` — reentrenado ${formatDate(activeModel.trained_at)}`
                      : ""
                  }`}
                </TooltipContent>
              </Tooltip>
            )}
          </div>
          <div className="space-y-1.5">
            {sortedScores.map(([tech, score]) => (
              <TechScoreRow
                key={tech}
                tech={tech}
                score={score}
                model={model}
                isSelected={chosenTech === tech}
                isSecondary={chosenSecs.has(tech)}
                onSelect={(shiftKey) => onSelectTech(tech, shiftKey)}
              />
            ))}
          </div>
          <p className="text-tf-micro text-muted-foreground mt-1">
            Clic: principal · Mayús + clic: secundaria · La marca vertical es el umbral del modelo
          </p>
        </div>
      )}

      {!model && prob == null && (
        <p className="text-tf-meta text-muted-foreground">
          Sin predicción del modelo para esta licitación.
        </p>
      )}
    </>
  );
}
