"use client";

/**
 * Decidir el GO/NO-GO **desde donde se está mirando** la oportunidad.
 *
 * La decisión solo se podía tomar en la ficha y solo en la fase «Decisión»:
 * llegar hasta ahí desde «Identificada» eran dos cambios de fase previos, y un
 * equipo pequeño no los daba —las oportunidades se quedaban sin decidir hasta
 * que el plazo pasaba—. Aquí la decisión cuesta una elección y un motivo, y
 * lleva la oportunidad a donde la propia decisión manda: el GO a «Preparando
 * oferta» (la API deja saltar las fases previas cuando hay GO) y el NO-GO a
 * retirada.
 *
 * El motivo no es opcional: la API rechaza una decisión sin él, y es lo único
 * que explica en el historial por qué se fue o no se fue a una licitación.
 *
 * El NO-GO no tiene deshacer —`withdrawn` es terminal— y por eso se avisa en la
 * propia capa, antes de guardar: elegirlo, escribir el motivo y pulsar ya son
 * tres gestos deliberados, y un diálogo de confirmación encima sería el cuarto.
 */

import * as React from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { decisionLabel, statusLabel } from "@/components/pursuits/pursuit-presenters";
import type { UpdatePursuitInput } from "@/hooks/use-pursuits";
import { cn } from "@/lib/utils";

export type DecisionTomada = "go" | "no_go";

export interface Decision {
  decision: DecisionTomada;
  motivo: string;
}

const OPCIONES: readonly DecisionTomada[] = ["go", "no_go"];

/**
 * El PATCH que registra la decisión **y** mueve la oportunidad con ella, en un
 * solo cambio. El NO-GO se cierra como «No presentada»: es lo que afirma, y la
 * razón concreta viaja en el motivo de la decisión.
 */
export function cambioDeDecision(
  { decision, motivo }: Decision,
  expectedVersion: number,
): UpdatePursuitInput {
  if (decision === "go") {
    return {
      status: "preparing",
      decision: "go",
      decision_reason: motivo,
      expected_version: expectedVersion,
    };
  }
  return {
    status: "withdrawn",
    outcome: "cancelled",
    outcome_reason_code: "no_presentada",
    decision: "no_go",
    decision_reason: motivo,
    expected_version: expectedVersion,
  };
}

export function DecidirGoNoGo({
  etiqueta = "Decidir",
  guardando,
  onGuardar,
  className,
}: {
  etiqueta?: string;
  guardando: boolean;
  /** `alGuardar` se llama cuando la API confirma: es lo que cierra la capa. */
  onGuardar: (decision: Decision, alGuardar: () => void) => void;
  className?: string;
}) {
  const [abierto, setAbierto] = React.useState(false);
  const [decision, setDecision] = React.useState<DecisionTomada | null>(null);
  const [motivo, setMotivo] = React.useState("");
  const texto = motivo.trim();

  const guardar = (event: React.FormEvent) => {
    event.preventDefault();
    if (!decision || !texto) return;
    onGuardar({ decision, motivo: texto }, () => {
      setAbierto(false);
      setDecision(null);
      setMotivo("");
    });
  };

  return (
    <Popover open={abierto} onOpenChange={setAbierto}>
      <PopoverTrigger asChild>
        <button
          type="button"
          // Dentro de una fila que se selecciona al pulsarla, el botón no tiene
          // por qué seleccionarla.
          onClick={(event) => event.stopPropagation()}
          className={cn(
            buttonVariants({ variant: "outline", size: "sm" }),
            "truncate border-primary/30 bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary",
            className,
          )}
        >
          {etiqueta}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[320px] max-w-[calc(100vw-2rem)] p-3"
        // La capa se pinta fuera de la fila pero sus eventos burbujean por el
        // árbol de React hasta ella.
        onClick={(event) => event.stopPropagation()}
        onDoubleClick={(event) => event.stopPropagation()}
      >
        <form onSubmit={guardar} className="space-y-2.5">
          <h3 className="text-tf-body font-semibold">Decisión</h3>
          <div className="flex gap-1.5">
            {OPCIONES.map((opcion) => (
              <button
                key={opcion}
                type="button"
                aria-pressed={decision === opcion}
                onClick={() => setDecision(opcion)}
                className={cn(
                  "tf-pressable h-8 flex-1 rounded-md border px-4 text-tf-body font-semibold",
                  decision === opcion
                    ? opcion === "go"
                      ? "border-success/50 bg-success/10 text-success"
                      : "border-destructive/50 bg-destructive/10 text-destructive"
                    : "border-input text-muted-foreground hover:text-foreground",
                )}
              >
                {decisionLabel(opcion)}
              </button>
            ))}
          </div>
          <Textarea
            aria-label="Motivo de la decisión"
            rows={2}
            value={motivo}
            onChange={(event) => setMotivo(event.target.value)}
            placeholder="Por qué se va o no se va a esta licitación"
            maxLength={2000}
          />
          <div className="flex items-center gap-2">
            <p className="flex-1 text-tf-micro text-muted-foreground">
              {decision === "no_go"
                ? "La oportunidad se retira y sale de la agenda. No se puede reabrir."
                : decision === "go"
                  ? `Pasa a «${statusLabel("preparing")}».`
                  : "El GO y el NO-GO exigen motivo."}
            </p>
            <Button type="submit" size="sm" disabled={!decision || !texto || guardando}>
              {guardando ? "Guardando…" : "Guardar decisión"}
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}
