"use client";

import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { plazoVisual } from "@/components/pursuits/pursuit-presenters";
import { useUpdatePursuit, type Pursuit } from "@/hooks/use-pursuits";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

/**
 * `next_action` y su vencimiento: qué toca hacer aquí y cuándo.
 *
 * Es el dato que hace medible el abandono, y hasta ahora sólo se editaba desde
 * la agenda de Mi Pipeline: quien abría la ficha para decidir tenía que salir a
 * otra pantalla para apuntar el siguiente paso. La banda roja no es decoración:
 * sale de la misma rampa `--urgency-*` que el plazo de la tarjeta, y aparece
 * cuando vence hoy o mañana.
 */
export function ProximaAccion({ pursuit }: { pursuit: Pursuit }) {
  const actualizar = useUpdatePursuit(pursuit.id);
  const [editando, setEditando] = React.useState(false);
  const [accion, setAccion] = React.useState(pursuit.next_action ?? "");
  const [vence, setVence] = React.useState(pursuit.next_action_due ?? "");
  const accionId = React.useId();
  const venceId = React.useId();

  const plazo = plazoVisual(pursuit.next_action_due);
  const urgente = plazo != null && plazo.dias <= 1;
  // `plazo.texto` habla del plazo de presentación («3 d para cierre»), que no
  // es lo que vence aquí.
  const vencimiento =
    plazo == null
      ? "Sin fecha"
      : plazo.dias < 0
        ? `Vencida hace ${Math.abs(plazo.dias)} d`
        : plazo.dias === 0
          ? "Vence hoy"
          : `Vence en ${plazo.dias} d`;

  const guardar = () => {
    actualizar.mutate(
      {
        next_action: accion.trim() || null,
        next_action_due: vence || null,
        expected_version: pursuit.version,
      },
      {
        onSuccess: () => {
          setEditando(false);
          toast.success("Próxima acción guardada");
        },
        onError: (error) =>
          toast.error(
            error instanceof ApiError && error.status === 409
              ? "Alguien del equipo la cambió mientras la tenías abierta"
              : "No se pudo guardar la próxima acción",
            { description: error instanceof Error ? error.message : undefined },
          ),
      },
    );
  };

  return (
    <section
      aria-label="Próxima acción"
      className={cn(
        "rounded-xl border px-4 py-3",
        urgente
          ? "border-[hsl(var(--urgency-critical)/0.3)] bg-[hsl(var(--urgency-critical)/0.06)]"
          : "border-border/60 bg-card/70",
      )}
    >
      {editando ? (
        <div className="flex flex-col gap-2">
          <div>
            <label htmlFor={accionId} className="text-muted-foreground mb-1 block text-tf-micro">
              Qué toca hacer
            </label>
            <Input
              id={accionId}
              value={accion}
              maxLength={300}
              onChange={(event) => setAccion(event.target.value)}
              placeholder="Ej. Convocar el comité de GO/NO-GO"
            />
          </div>
          <div>
            <label htmlFor={venceId} className="text-muted-foreground mb-1 block text-tf-micro">
              Cuándo vence
            </label>
            <Input
              id={venceId}
              type="date"
              value={vence}
              onChange={(event) => setVence(event.target.value)}
            />
          </div>
          <div className="flex items-center gap-2">
            <div className="flex-1" />
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setAccion(pursuit.next_action ?? "");
                setVence(pursuit.next_action_due ?? "");
                setEditando(false);
              }}
            >
              Cancelar
            </Button>
            <Button size="sm" disabled={actualizar.isPending} onClick={guardar}>
              Guardar
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden="true"
            className={cn(
              "h-1.5 w-1.5 flex-none rounded-full",
              urgente ? "bg-[hsl(var(--urgency-critical))]" : "bg-muted-foreground",
            )}
          />
          <div className="min-w-0 flex-1">
            {pursuit.next_action ? (
              <>
                <p className="truncate text-tf-body font-semibold">{pursuit.next_action}</p>
                <p className="text-muted-foreground mt-0.5 text-tf-micro">
                  {vencimiento} · {pursuit.responsible_name ?? "Sin responsable"}
                </p>
              </>
            ) : (
              <p className="text-muted-foreground text-tf-body">
                Sin próxima acción. Sin ella, nadie sabe qué toca aquí.
              </p>
            )}
          </div>
          <Button variant="outline" size="sm" onClick={() => setEditando(true)}>
            {pursuit.next_action ? "Editar" : "Añadir"}
          </Button>
        </div>
      )}
    </section>
  );
}
