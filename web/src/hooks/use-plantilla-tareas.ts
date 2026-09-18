"use client";

/**
 * F4.6 — plantilla de tareas que se crean al pasar una oportunidad a
 * «preparando oferta». Cualquier miembro la ve; `puede_editar` (del backend)
 * dice si además la cambia, así que la pantalla no ofrece un formulario que
 * acabe en 403.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { organizationKeys } from "@/lib/query-keys";

export type PlantillaTareas = Schemas["PlantillaTareasOut"];
export type TareaPlantilla = Schemas["TareaPlantilla"];

export function usePlantillaTareas(organizationId: number | null) {
  return useQuery({
    queryKey: organizationKeys.plantillaTareas(organizationId),
    queryFn: () =>
      fetchWithAuth<PlantillaTareas>(`/api/v1/organizations/${organizationId}/plantilla-tareas`),
    enabled: organizationId != null,
  });
}

export function useGuardarPlantillaTareas(organizationId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (tareas: TareaPlantilla[]) =>
      apiMutate<PlantillaTareas>(
        "PUT",
        `/api/v1/organizations/${organizationId}/plantilla-tareas`,
        { tareas },
      ),
    onSuccess: (plantilla) => {
      queryClient.setQueryData(organizationKeys.plantillaTareas(organizationId), plantilla);
    },
  });
}

export interface FilaPlantilla {
  titulo: string;
  /** Texto del input: vacío = sin plazo. */
  dias: string;
}

/**
 * Filas del formulario → cuerpo del PUT, o el primer error. Las filas con el
 * título vacío se descartan (son filas a medio escribir, no tareas); un plazo
 * que no es un entero entre 0 y 365 es un error, no un «sin plazo»: tratarlo
 * así borraría en silencio lo que el usuario quiso escribir.
 */
export function filasATareas(
  filas: readonly FilaPlantilla[],
  max: number,
): { tareas: TareaPlantilla[]; error: null } | { tareas: null; error: string } {
  const tareas: TareaPlantilla[] = [];
  for (const [indice, fila] of filas.entries()) {
    const titulo = fila.titulo.trim();
    if (!titulo) continue;
    const dias = fila.dias.trim();
    if (dias && !/^\d{1,3}$/.test(dias)) {
      return { tareas: null, error: `Tarea ${indice + 1}: el plazo tiene que ser un número de días.` };
    }
    const n = dias ? Number(dias) : null;
    if (n != null && n > 365) {
      return { tareas: null, error: `Tarea ${indice + 1}: el plazo no puede pasar de 365 días.` };
    }
    tareas.push({ titulo, dias_antes_limite: n });
  }
  if (tareas.length > max) {
    return { tareas: null, error: `La plantilla admite como mucho ${max} tareas.` };
  }
  return { tareas, error: null };
}

export function tareasAFilas(tareas: readonly TareaPlantilla[]): FilaPlantilla[] {
  return tareas.map((t) => ({
    titulo: t.titulo,
    dias: t.dias_antes_limite == null ? "" : String(t.dias_antes_limite),
  }));
}
