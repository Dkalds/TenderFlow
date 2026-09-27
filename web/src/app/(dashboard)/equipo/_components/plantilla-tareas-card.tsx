"use client";

/**
 * F4.6 — plantilla de tareas por etapa, en Equipo → Organización.
 *
 * Las tareas se crean **una vez** cuando una oportunidad pasa a «preparando
 * oferta», con el plazo contado hacia atrás desde la fecha límite. El
 * propietario y los administradores la editan; el resto la ve en sólo lectura
 * (`puede_editar` lo decide el backend, no el rol que crea tener la pantalla).
 */
import * as React from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Panel, PanelError, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type FilaPlantilla,
  type PlantillaTareas,
  filasATareas,
  tareasAFilas,
  useGuardarPlantillaTareas,
  usePlantillaTareas,
} from "@/hooks/use-plantilla-tareas";
import { getErrorMessage } from "@/lib/query-feedback";

export function PlantillaTareasCard({ organizationId }: { organizationId: number }) {
  const { data, isLoading, error, refetch } = usePlantillaTareas(organizationId);

  return (
    <Panel>
      <PanelTitle title="Tareas al preparar una oferta" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Cuando una oportunidad pasa a «Preparando oferta» se crean estas tareas, una sola vez. El plazo se cuenta
        en días antes de la fecha límite del expediente.
      </p>
      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : error || !data ? (
        <PanelError
          variant="inline"
          title="No se pudo cargar la plantilla de tareas"
          error={error ?? undefined}
          onRetry={() => void refetch()}
        />
      ) : data.puede_editar ? (
        <EditorPlantilla key={JSON.stringify(data.tareas)} organizationId={organizationId} plantilla={data} />
      ) : (
        <LecturaPlantilla plantilla={data} />
      )}
    </Panel>
  );
}

function LecturaPlantilla({ plantilla }: { plantilla: PlantillaTareas }) {
  const tareas = plantilla.tareas ?? [];
  if (tareas.length === 0) {
    return (
      <p className="text-tf-meta text-muted-foreground">
        Tu organización no tiene plantilla. Un propietario o un administrador puede crearla.
      </p>
    );
  }
  return (
    <ol className="list-decimal space-y-1 pl-5 text-tf-body">
      {tareas.map((tarea, i) => (
        <li key={`${i}-${tarea.titulo}`}>
          {tarea.titulo}
          <span className="text-muted-foreground">
            {tarea.dias_antes_limite == null
              ? " · sin plazo"
              : ` · ${tarea.dias_antes_limite} días antes de la fecha límite`}
          </span>
        </li>
      ))}
    </ol>
  );
}

function EditorPlantilla({
  organizationId,
  plantilla,
}: {
  organizationId: number;
  plantilla: PlantillaTareas;
}) {
  const max = plantilla.max_tareas ?? 20;
  const [filas, setFilas] = React.useState<FilaPlantilla[]>(() => tareasAFilas(plantilla.tareas ?? []));
  const [error, setError] = React.useState<string | null>(null);
  const guardar = useGuardarPlantillaTareas(organizationId);

  const cambiar = (indice: number, campo: keyof FilaPlantilla, valor: string) =>
    setFilas((actuales) => actuales.map((f, i) => (i === indice ? { ...f, [campo]: valor } : f)));

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const resultado = filasATareas(filas, max);
    if (resultado.error !== null) {
      setError(resultado.error);
      return;
    }
    setError(null);
    try {
      await guardar.mutateAsync(resultado.tareas);
      toast.success("Plantilla de tareas guardada");
    } catch (err) {
      toast.error(getErrorMessage(err, "accion"));
    }
  };

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      {filas.length === 0 ? (
        <p className="text-tf-meta text-muted-foreground">
          Sin tareas: las oportunidades que pasen a «Preparando oferta» no recibirán ninguna.
        </p>
      ) : (
        <ol className="space-y-2">
          {filas.map((fila, i) => (
            <li key={i} className="flex flex-wrap items-end gap-2">
              <Field label={`Tarea ${i + 1}`} htmlFor={`plantilla-${organizationId}-${i}-titulo`} className="min-w-56 flex-1">
                <Input
                  id={`plantilla-${organizationId}-${i}-titulo`}
                  value={fila.titulo}
                  maxLength={300}
                  onChange={(event) => cambiar(i, "titulo", event.target.value)}
                  placeholder="p. ej. Revisión legal del pliego"
                />
              </Field>
              <Field label="Días antes del límite" htmlFor={`plantilla-${organizationId}-${i}-dias`} className="w-40">
                <Input
                  id={`plantilla-${organizationId}-${i}-dias`}
                  value={fila.dias}
                  inputMode="numeric"
                  onChange={(event) => cambiar(i, "dias", event.target.value)}
                  placeholder="Sin plazo"
                />
              </Field>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Quitar tarea ${i + 1}`}
                onClick={() => setFilas((actuales) => actuales.filter((_, j) => j !== i))}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ol>
      )}
      {error ? (
        <p role="alert" className="text-tf-meta text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={filas.length >= max}
          onClick={() => setFilas((actuales) => [...actuales, { titulo: "", dias: "" }])}
        >
          <Plus aria-hidden="true" />
          Añadir tarea
        </Button>
        <Button type="submit" size="sm" disabled={guardar.isPending}>
          {guardar.isPending ? "Guardando…" : "Guardar plantilla"}
        </Button>
        <span className="text-tf-meta text-muted-foreground">
          {filas.length} de {max} tareas. Cambiarla no toca las tareas ya creadas.
        </span>
      </div>
    </form>
  );
}
