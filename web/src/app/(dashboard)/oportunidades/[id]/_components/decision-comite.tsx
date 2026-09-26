"use client";

import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { SectionTitle } from "@/components/console/panel";
import { decisionLabel } from "@/components/pursuits/pursuit-presenters";
import { useUpdatePursuit, type Pursuit, type PursuitDecision } from "@/hooks/use-pursuits";
import { ApiError } from "@/lib/api-client";
import { EMPTY, cn, formatDate } from "@/lib/utils";

const OPCIONES: readonly PursuitDecision[] = ["go", "no_go"];

/**
 * El GO/NO-GO, con su motivo, donde se toma: en la fase «Decisión».
 *
 * Fuera de esa fase se lee pero no se edita, y no por gusto de bloquear: el
 * backend exige GO para preparar o presentar, y un NO-GO sólo lo admite
 * mientras la oportunidad está en «Decisión» o retirada
 * (`services/pursuits.py`). Ofrecer los botones antes o después sería ofrecer
 * un 422. Para los casos raros —corregir una decisión de una oportunidad ya
 * avanzada— sigue estando el formulario completo de «Todos los campos».
 *
 * El motivo no es opcional: el backend rechaza una decisión sin él, y es lo
 * único que explica en el historial por qué se fue o no se fue a esta
 * licitación.
 *
 * Antes de llegar a «Decisión», y sin decisión tomada, es una sola línea: un
 * bloque entero que solo decía «todavía no» ocupaba el segundo puesto de la
 * ficha en las dos fases en que no se puede hacer nada con él.
 */
export function DecisionComite({ pursuit }: { pursuit: Pursuit }) {
  const editable = pursuit.status === "go_no_go";
  const todaviaNo =
    pursuit.decision === "pending" && (pursuit.status === "identified" || pursuit.status === "qualifying");
  const actualizar = useUpdatePursuit(pursuit.id);
  const [decision, setDecision] = React.useState<PursuitDecision>(pursuit.decision);
  const [motivo, setMotivo] = React.useState(pursuit.decision_reason ?? "");
  const motivoId = React.useId();

  const sucio =
    decision !== pursuit.decision || motivo.trim() !== (pursuit.decision_reason ?? "").trim();
  const faltaMotivo = decision !== "pending" && motivo.trim() === "";

  const estado =
    pursuit.decision === "pending"
      ? "Sin decidir"
      : `${decisionLabel(pursuit.decision)}${
          pursuit.decision_at ? ` · ${formatDate(pursuit.decision_at)}` : ""
        }`;

  const guardar = () => {
    actualizar.mutate(
      {
        decision,
        decision_reason: motivo.trim() || null,
        expected_version: pursuit.version,
      },
      {
        onSuccess: () => toast.success("Decisión guardada"),
        onError: (error) =>
          toast.error(
            error instanceof ApiError && error.status === 409
              ? "Alguien del equipo la cambió mientras la tenías abierta"
              : "No se pudo guardar la decisión",
            { description: error instanceof Error ? error.message : undefined },
          ),
      },
    );
  };

  if (todaviaNo) {
    return (
      <section
        id="ficha-decision"
        tabIndex={-1}
        aria-label="Decisión del comité"
        className="border-border/60 flex flex-wrap items-baseline gap-x-2.5 gap-y-1 rounded-xl border border-dashed px-4 py-2.5 outline-none"
      >
        <h4 className="text-muted-foreground font-mono text-tf-micro font-semibold tracking-wider uppercase">
          Decisión del comité
        </h4>
        <p className="text-muted-foreground text-tf-micro">
          Se toma en la fase «Decisión». Hasta entonces, sin decidir.
        </p>
      </section>
    );
  }

  return (
    <section
      id="ficha-decision"
      tabIndex={-1}
      aria-label="Decisión del comité"
      className="border-border/60 bg-card/70 rounded-xl border px-4 py-3.5 outline-none"
    >
      <SectionTitle aside={estado}>Decisión del comité</SectionTitle>

      {editable ? (
        <>
          <div className="mb-3 flex gap-1.5">
            {OPCIONES.map((opcion) => (
              <button
                key={opcion}
                type="button"
                aria-pressed={decision === opcion}
                onClick={() => setDecision(decision === opcion ? "pending" : opcion)}
                className={cn(
                  "h-8 rounded-md border px-5 text-tf-body font-semibold transition-colors",
                  decision === opcion
                    ? opcion === "go"
                      ? "border-[hsl(var(--success))] bg-success/14 text-success"
                      : "border-destructive bg-destructive/12 text-destructive"
                    : "border-input text-muted-foreground hover:text-foreground",
                )}
              >
                {decisionLabel(opcion)}
              </button>
            ))}
          </div>

          <label htmlFor={motivoId} className="text-muted-foreground mb-1 block text-tf-micro">
            Motivo de la decisión
          </label>
          <Textarea
            id={motivoId}
            rows={2}
            value={motivo}
            onChange={(event) => setMotivo(event.target.value)}
            placeholder="Por qué se va o no se va a esta licitación"
          />

          <div className="mt-2.5 flex items-center gap-2">
            <p className="text-muted-foreground flex-1 text-tf-micro leading-[1.4]">
              {faltaMotivo
                ? "El GO y el NO-GO exigen motivo."
                : "Con el NO-GO, la oportunidad solo puede retirarse."}
            </p>
            <Button
              size="sm"
              disabled={!sucio || faltaMotivo || actualizar.isPending}
              onClick={guardar}
            >
              Guardar decisión
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className="text-tf-body leading-[1.45]">
            {pursuit.decision === "pending"
              ? "Sin decidir todavía."
              : (pursuit.decision_reason ?? EMPTY)}
          </p>
          <p className="text-muted-foreground mt-1.5 text-tf-micro leading-[1.4]">
            {pursuit.status === "identified" || pursuit.status === "qualifying"
              ? "Se registra al llegar a la fase «Decisión»."
              : "Corregirla ahora se hace en «Editar todos los campos»."}
          </p>
        </>
      )}
    </section>
  );
}
