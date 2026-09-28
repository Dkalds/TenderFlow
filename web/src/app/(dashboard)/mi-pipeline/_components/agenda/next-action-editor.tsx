"use client";

/**
 * Editor de próxima acción de una oportunidad — el dato que hace medible el
 * abandono.
 *
 * **Sigue existiendo aunque ya haya tareas, y no es una duplicación.** Desde
 * C6.1 `next_action` se *deriva* de la tarea abierta más urgente: crear,
 * completar o borrar una tarea la recalcula la API
 * (`services/pursuit_tasks.py`). Pero editarla a mano sigue siendo posible y es
 * lo que sostiene dos casos reales: la oportunidad que todavía no tiene ninguna
 * tarea —escribir aquí el siguiente paso es más barato que abrir una ficha de
 * tarea— y la que necesita una nota que no es una tarea asignable a nadie.
 * Guardar aquí **pisa** el valor derivado hasta que la siguiente tarea lo
 * recalcule; por eso la fila de esa acción manual aparece en la agenda con
 * `tarea_id` nulo.
 *
 * Va como componente aparte y montado con `key` por selección/versión: cambiar
 * de fila remonta el editor con el valor del servidor, sin efectos que
 * sincronicen estado (react-hooks).
 */

import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { getErrorMessage } from "@/lib/query-feedback";
import { type PipelineAgendaItem, useUpdatePursuit } from "@/hooks/use-pursuits";

export function NextActionEditor({
  item,
  enfoque = 0,
}: {
  item: PipelineAgendaItem;
  /**
   * Contador de peticiones de foco desde la lista («Editar acción», o la tecla
   * `C` sobre una acción manual). Un booleano no serviría: pedirlo dos veces
   * sobre la misma fila no cambiaría el valor y el segundo gesto no enfocaría.
   */
  enfoque?: number;
}) {
  const updatePursuit = useUpdatePursuit(item.pursuit_id ?? "");
  const [accion, setAccion] = React.useState(item.next_action ?? "");
  const [vence, setVence] = React.useState(item.next_action_due ?? "");
  const campo = React.useRef<HTMLInputElement>(null);
  const accionId = React.useId();
  const venceId = React.useId();

  React.useEffect(() => {
    if (enfoque > 0) campo.current?.focus();
  }, [enfoque]);

  const dirty = accion !== (item.next_action ?? "") || vence !== (item.next_action_due ?? "");

  const guardar = () => {
    if (item.version == null) return;
    updatePursuit.mutate(
      {
        next_action: accion.trim() || null,
        next_action_due: vence || null,
        expected_version: item.version,
      },
      {
        onSuccess: () => toast.success("Próxima acción guardada"),
        onError: (err) =>
          toast.error("No se pudo guardar la próxima acción", { description: getErrorMessage(err, "accion") }),
      },
    );
  };

  return (
    <div>
      <Field label="Editar la próxima acción a mano" htmlFor={accionId} className="mb-2">
        <Input
          id={accionId}
          ref={campo}
          value={accion}
          onChange={(event) => setAccion(event.target.value)}
          placeholder="p. ej. preparar el borrador de la oferta"
          maxLength={300}
          className="h-8 text-tf-meta"
        />
      </Field>
      <label htmlFor={venceId} className="sr-only">
        Fecha límite de la próxima acción
      </label>
      <Input
        id={venceId}
        type="date"
        value={vence}
        onChange={(event) => setVence(event.target.value)}
        className="mb-2 h-8 text-tf-meta"
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!dirty || updatePursuit.isPending}
        onClick={guardar}
        className="w-full border-primary/30 bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary"
      >
        {updatePursuit.isPending ? "Guardando…" : "Guardar"}
      </Button>
    </div>
  );
}
