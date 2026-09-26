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
 * la Agenda (`/mi-pipeline`): quien abría la ficha para decidir tenía que salir a
 * otra pantalla para apuntar el siguiente paso. La banda roja no es decoración:
 * sale de la misma rampa `--urgency-*` que el plazo de la tarjeta, y aparece
 * cuando vence hoy o mañana.
 *
 * Si está en edición lo decide la ficha (`editando`), porque también la abre el
 * paso «Próxima acción planificada» del bloque de salida, que vive en la otra
 * columna. Al abrirse, el foco va al primer campo.
 */
export function ProximaAccion({
  pursuit,
  editando,
  onEditar,
}: {
  pursuit: Pursuit;
  editando: boolean;
  onEditar: (abierto: boolean) => void;
}) {
  const actualizar = useUpdatePursuit(pursuit.id);
  const [accion, setAccion] = React.useState(pursuit.next_action ?? "");
  const [vence, setVence] = React.useState(pursuit.next_action_due ?? "");
  const accionId = React.useId();
  const venceId = React.useId();
  const primerCampo = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (editando) primerCampo.current?.focus();
  }, [editando]);

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

  const cancelar = () => {
    setAccion(pursuit.next_action ?? "");
    setVence(pursuit.next_action_due ?? "");
    onEditar(false);
  };
  const alEscape = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") cancelar();
  };

  const guardar = () => {
    actualizar.mutate(
      {
        next_action: accion.trim() || null,
        next_action_due: vence || null,
        expected_version: pursuit.version,
      },
      {
        onSuccess: () => {
          onEditar(false);
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
      id="ficha-proxima-accion"
      aria-label="Próxima acción"
      className={cn(
        "rounded-xl border px-4 py-3",
        urgente
          ? "border-[hsl(var(--urgency-critical)/0.3)] bg-[hsl(var(--urgency-critical)/0.06)]"
          : "border-border/60 bg-card/70",
      )}
    >
      {editando ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            guardar();
          }}
        >
          <div>
            <label htmlFor={accionId} className="text-muted-foreground mb-1 block text-tf-micro">
              Qué toca hacer
            </label>
            <Input
              ref={primerCampo}
              id={accionId}
              value={accion}
              maxLength={300}
              onChange={(event) => setAccion(event.target.value)}
              onKeyDown={alEscape}
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
              onKeyDown={alEscape}
            />
          </div>
          <div className="flex items-center gap-2">
            <div className="flex-1" />
            <Button type="button" variant="outline" size="sm" onClick={cancelar}>
              Cancelar
            </Button>
            <Button type="submit" size="sm" disabled={actualizar.isPending}>
              Guardar
            </Button>
          </div>
        </form>
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
          <Button variant="outline" size="sm" onClick={() => onEditar(true)}>
            {pursuit.next_action ? "Editar" : "Añadir"}
          </Button>
        </div>
      )}
    </section>
  );
}
