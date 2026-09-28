"use client";

/**
 * Las tareas de una oportunidad, dentro del inspector de la agenda.
 *
 * **Es la primera pantalla de C6.1 en todo el producto**: las rutas
 * `/pursuits/{id}/tasks` existían desde la migración que creó la tabla y no las
 * pintaba nadie, así que el trabajo que la gente se apuntaba sólo se veía
 * reducido a la `next_action` que la API deriva de ellas. Aquí se ven las
 * tareas de verdad, se cierran con un clic y se añade una sin salir de la lista.
 *
 * Completar una tarea recalcula `next_action` en servidor; el hook invalida la
 * raíz `pursuits` entera para que la agenda de al lado no se quede con la
 * anterior.
 */

import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { PanelError, SectionTitle } from "@/components/console/panel";
import { getErrorMessage } from "@/lib/query-feedback";
import { cn, formatDate } from "@/lib/utils";
import {
  tareaAbierta,
  useActualizarTarea,
  useCrearTarea,
  usePursuitTasks,
  type PursuitTask,
} from "@/hooks/use-pursuit-tasks";

function FilaTarea({ tarea, pursuitId }: { tarea: PursuitTask; pursuitId: number }) {
  const actualizar = useActualizarTarea();
  const abierta = tareaAbierta(tarea);
  const etiquetaId = React.useId();

  const alternar = () => {
    const estado = abierta ? "hecha" : "pendiente";
    actualizar.mutate(
      { pursuitId, taskId: tarea.id, estado },
      {
        onError: (err) =>
          toast.error("No se pudo actualizar la tarea", { description: getErrorMessage(err, "accion") }),
      },
    );
  };

  return (
    <li className="flex items-start gap-2 py-1">
      <Checkbox
        checked={!abierta}
        onCheckedChange={alternar}
        disabled={actualizar.isPending}
        aria-labelledby={etiquetaId}
        className="mt-0.5 h-3.5 w-3.5"
      />
      <div className="min-w-0 flex-1">
        <span
          id={etiquetaId}
          className={cn(
            "block text-tf-meta",
            abierta ? "text-foreground" : "text-muted-foreground line-through",
          )}
        >
          {tarea.titulo}
        </span>
        {(tarea.vence || tarea.responsable_name) && (
          <span className="block text-tf-micro text-muted-foreground">
            {[tarea.vence ? formatDate(tarea.vence) : null, tarea.responsable_name]
              .filter(Boolean)
              .join(" · ")}
          </span>
        )}
      </div>
    </li>
  );
}

export function AgendaTareas({ pursuitId }: { pursuitId: number }) {
  const { data, isPending, error, refetch } = usePursuitTasks(pursuitId);
  const crear = useCrearTarea();
  const [titulo, setTitulo] = React.useState("");
  const [vence, setVence] = React.useState("");
  const tituloId = React.useId();
  const venceId = React.useId();

  const tareas = data ?? [];
  const abiertas = tareas.filter(tareaAbierta).length;

  const anadir = (event: React.FormEvent) => {
    event.preventDefault();
    const texto = titulo.trim();
    if (!texto) return;
    crear.mutate(
      { pursuitId, titulo: texto, vence: vence || null },
      {
        onSuccess: () => {
          setTitulo("");
          setVence("");
          toast.success("Tarea añadida");
        },
        onError: (err) =>
          toast.error("No se pudo crear la tarea", { description: getErrorMessage(err, "accion") }),
      },
    );
  };

  return (
    <div>
      <SectionTitle hint={tareas.length ? `${abiertas} abiertas` : undefined}>Tareas</SectionTitle>

      {error ? (
        <PanelError
          variant="inline"
          className="py-0"
          title="No se pudieron cargar las tareas"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : isPending ? (
        <p role="status" className="text-tf-micro text-muted-foreground">
          Cargando tareas…
        </p>
      ) : tareas.length === 0 ? (
        <p className="text-tf-meta text-muted-foreground">
          Sin tareas. La primera que añadas pasa a ser la próxima acción.
        </p>
      ) : (
        <ul className="mb-2 divide-y divide-border/40">
          {tareas.map((tarea) => (
            <FilaTarea key={tarea.id} tarea={tarea} pursuitId={pursuitId} />
          ))}
        </ul>
      )}

      <form onSubmit={anadir} className="mt-2 space-y-1.5">
        <label htmlFor={tituloId} className="sr-only">
          Nueva tarea
        </label>
        <Input
          id={tituloId}
          value={titulo}
          onChange={(event) => setTitulo(event.target.value)}
          placeholder="Añadir una tarea"
          maxLength={300}
          className="h-8 text-tf-meta"
        />
        <div className="flex gap-1.5">
          <label htmlFor={venceId} className="sr-only">
            Fecha de la nueva tarea
          </label>
          <Input
            id={venceId}
            type="date"
            value={vence}
            onChange={(event) => setVence(event.target.value)}
            className="h-8 flex-1 text-tf-meta"
          />
          <Button
            type="submit"
            variant="outline"
            size="sm"
            disabled={!titulo.trim() || crear.isPending}
            className="flex-none border-primary/30 bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary md:h-8"
          >
            {crear.isPending ? "Añadiendo…" : "Añadir"}
          </Button>
        </div>
      </form>
    </div>
  );
}
