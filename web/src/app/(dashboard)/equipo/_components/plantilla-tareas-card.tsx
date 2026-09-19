"use client";

/**
 * F4.6 — plantilla de tareas por etapa, en Equipo → Organización.
 *
 * Las tareas se crean **una vez** cuando una oportunidad pasa a «preparando
 * oferta», con el plazo contado hacia atrás desde la fecha límite. Owner y
 * admin la editan; el resto la ve en sólo lectura (`puede_editar` lo decide
 * el backend, no el rol que crea tener la pantalla).
 */
import * as React from "react";
import { ListChecks, Loader2, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

export function PlantillaTareasCard({ organizationId }: { organizationId: number }) {
  const { data, isLoading, isError } = usePlantillaTareas(organizationId);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ListChecks className="h-4 w-4 text-primary" aria-hidden="true" />
          Tareas al preparar una oferta
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Cuando una oportunidad pasa a «Preparando oferta» se crean estas tareas, una sola vez.
          El plazo se cuenta en días antes de la fecha límite del expediente.
        </p>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : isError || !data ? (
          <p role="alert" className="text-sm text-destructive">
            No se pudo cargar la plantilla de tareas.
          </p>
        ) : data.puede_editar ? (
          <EditorPlantilla key={JSON.stringify(data.tareas)} organizationId={organizationId} plantilla={data} />
        ) : (
          <LecturaPlantilla plantilla={data} />
        )}
      </CardContent>
    </Card>
  );
}

function LecturaPlantilla({ plantilla }: { plantilla: PlantillaTareas }) {
  const tareas = plantilla.tareas ?? [];
  if (tareas.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Tu organización no tiene plantilla. Un owner o admin puede crearla.
      </p>
    );
  }
  return (
    <ol className="list-decimal space-y-1 pl-5 text-sm">
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
      toast.error(err instanceof Error ? err.message : "No se pudo guardar la plantilla");
    }
  };

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      {filas.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Sin tareas: las oportunidades que pasen a «Preparando oferta» no recibirán ninguna.
        </p>
      ) : (
        <ol className="space-y-2">
          {filas.map((fila, i) => (
            <li key={i} className="flex flex-wrap items-end gap-2">
              <label
                htmlFor={`plantilla-${organizationId}-${i}-titulo`}
                className="min-w-56 flex-1 space-y-1 text-xs font-medium"
              >
                Tarea {i + 1}
                <Input
                  id={`plantilla-${organizationId}-${i}-titulo`}
                  value={fila.titulo}
                  maxLength={300}
                  onChange={(event) => cambiar(i, "titulo", event.target.value)}
                  placeholder="Revisión legal del pliego"
                />
              </label>
              <label
                htmlFor={`plantilla-${organizationId}-${i}-dias`}
                className="w-40 space-y-1 text-xs font-medium"
              >
                Días antes del límite
                <Input
                  id={`plantilla-${organizationId}-${i}-dias`}
                  value={fila.dias}
                  inputMode="numeric"
                  onChange={(event) => cambiar(i, "dias", event.target.value)}
                  placeholder="Sin plazo"
                />
              </label>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Quitar tarea ${i + 1}`}
                onClick={() => setFilas((actuales) => actuales.filter((_, j) => j !== i))}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ol>
      )}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
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
          <Plus className="h-4 w-4" aria-hidden="true" />
          Añadir tarea
        </Button>
        <Button type="submit" size="sm" disabled={guardar.isPending}>
          {guardar.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Save className="h-4 w-4" aria-hidden="true" />
          )}
          Guardar plantilla
        </Button>
        <span className="text-xs text-muted-foreground">
          {filas.length} de {max} tareas. Cambiarla no toca las tareas ya creadas.
        </span>
      </div>
    </form>
  );
}
