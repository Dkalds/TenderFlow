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
 *
 * **Lo escrito sin guardar sobrevive al cambio de fila.** El remontaje tiraba el
 * texto: un clic en otra fila, o J/K tras salir del campo, y la próxima acción
 * a medias se perdía sin aviso. Se guarda un borrador por oportunidad en
 * memoria (no sobrevive a recargar) y se recupera al volver, siempre que el
 * servidor siga teniendo el valor sobre el que se escribió: si otro lo cambió
 * entretanto, el borrador se descarta en vez de pisarlo.
 */

import * as React from "react";
import { toast } from "@/lib/toast";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { type PipelineAgendaItem, useUpdatePursuit } from "@/hooks/use-pursuits";

interface Borrador {
  accion: string;
  vence: string;
  /** Los valores del servidor sobre los que se escribió. */
  base: string;
}

const borradores = new Map<number, Borrador>();

const baseDe = (item: PipelineAgendaItem) =>
  JSON.stringify([item.next_action ?? "", item.next_action_due ?? ""]);

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
  const updatePursuit = useUpdatePursuit(item.pursuit_id ?? "", { errorTitle: "No se pudo guardar la próxima acción" });
  const pursuitId = item.pursuit_id;
  const [borrador] = React.useState(() => {
    const guardado = pursuitId == null ? undefined : borradores.get(pursuitId);
    return guardado?.base === baseDe(item) ? guardado : undefined;
  });
  const [accion, setAccion] = React.useState(borrador?.accion ?? item.next_action ?? "");
  const [vence, setVence] = React.useState(borrador?.vence ?? item.next_action_due ?? "");
  const campo = React.useRef<HTMLInputElement>(null);
  const accionId = React.useId();
  const venceId = React.useId();

  React.useEffect(() => {
    if (enfoque > 0) campo.current?.focus();
  }, [enfoque]);

  const dirty = accion !== (item.next_action ?? "") || vence !== (item.next_action_due ?? "");

  // Se escribe en el cambio, no al desmontar: en el remontaje por `key` el
  // valor nuevo ya está en la caché y la limpieza no sabría distinguirlo.
  const recordar = (siguienteAccion: string, siguienteVence: string) => {
    if (pursuitId == null) return;
    const limpio =
      siguienteAccion === (item.next_action ?? "") && siguienteVence === (item.next_action_due ?? "");
    if (limpio) borradores.delete(pursuitId);
    else borradores.set(pursuitId, { accion: siguienteAccion, vence: siguienteVence, base: baseDe(item) });
  };

  const guardar = () => {
    if (item.version == null) return;
    updatePursuit.mutate(
      {
        next_action: accion.trim() || null,
        next_action_due: vence || null,
        expected_version: item.version,
      },
      {
        onSuccess: () => {
          if (pursuitId != null) borradores.delete(pursuitId);
          toast.success("Próxima acción guardada");
        },
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
          onChange={(event) => {
            setAccion(event.target.value);
            recordar(event.target.value, vence);
          }}
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
        onChange={(event) => {
          setVence(event.target.value);
          recordar(accion, event.target.value);
        }}
        className="mb-2 h-8 text-tf-meta"
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!dirty || updatePursuit.isPending}
        onClick={guardar}
        className="w-full border-primary-line bg-primary-selected text-primary hover:bg-primary-soft hover:text-primary"
      >
        {updatePursuit.isPending ? "Guardando…" : "Guardar"}
      </Button>
      {dirty && !updatePursuit.isPending && (
        <p className="mt-1.5 text-tf-micro text-muted-foreground" role="status">
          {borrador ? "Borrador sin guardar, recuperado" : "Cambios sin guardar"}
        </p>
      )}
    </div>
  );
}
