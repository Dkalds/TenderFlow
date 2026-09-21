"use client";

/**
 * Tareas de una oportunidad (C6.1) — `GET|POST /pursuits/{id}/tasks` y
 * `PATCH|DELETE /pursuits/{id}/tasks/{task_id}`.
 *
 * Son el dato del que el backend **deriva** `next_action`: al crear, completar
 * o borrar una tarea, `services/pursuit_tasks.py` recalcula la próxima acción
 * de la oportunidad con la tarea abierta más urgente. Por eso las mutaciones
 * invalidan la raíz `pursuits` entera y no sólo su lista: la agenda, la ficha y
 * el tablero leen ese campo derivado y se quedarían con el valor de antes.
 *
 * La organización viaja como parámetro igual que en `usePursuit`: el backend la
 * resuelve sola si se omite, pero resolvería la personal, que no es la que se
 * está mirando. Y por lo mismo la consulta espera a saber cuál es
 * (`organizacionResuelta`) en vez de preguntar antes de tiempo.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import type { Schemas } from "@/lib/api-types";
import { organizationKeys, pursuitKeys } from "@/lib/query-keys";

export type PursuitTask = Schemas["PursuitTaskOut"];
export type PursuitTaskCreate = Schemas["PursuitTaskCreate"];
export type PursuitTaskPatch = Schemas["PursuitTaskPatch"];

/**
 * Los cuatro estados de `db/repositories/pursuit_tasks.py`. El esquema tipa
 * `estado` como `string` a secas —el backend no lo declara `Literal`—, así que
 * esta lista es lo único que impide mandar una etiqueta inventada que el
 * servidor rechazaría con 422 dejando la tarea sin tocar.
 */
export const ESTADOS_TAREA = ["pendiente", "en_curso", "hecha", "descartada"] as const;

export type EstadoTarea = (typeof ESTADOS_TAREA)[number];

/** Abierta = todavía cuenta como compromiso. Es el criterio del SQL. */
export function tareaAbierta(tarea: PursuitTask): boolean {
  return tarea.estado === "pendiente" || tarea.estado === "en_curso";
}

/** Query con la organización activa, o vacía mientras el backend la resuelve. */
function conOrganizacion(organizationId: number | null | undefined): string {
  const params = new URLSearchParams();
  if (organizationId != null) params.set("organization_id", String(organizationId));
  const query = params.toString();
  return query ? `?${query}` : "";
}

function rutaTareas(pursuitId: number | string, organizationId: number | null | undefined): string {
  return `/api/v1/pursuits/${encodeURIComponent(String(pursuitId))}/tasks${conOrganizacion(
    organizationId,
  )}`;
}

function rutaTarea(
  pursuitId: number,
  taskId: number,
  organizationId: number | null | undefined,
): string {
  return `/api/v1/pursuits/${encodeURIComponent(String(pursuitId))}/tasks/${taskId}${conOrganizacion(
    organizationId,
  )}`;
}

export function usePursuitTasks(pursuitId: number | null) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitKeys.tasks(pursuitId ?? ""), organizationId],
    queryFn: () => fetchWithAuth<PursuitTask[]>(rutaTareas(pursuitId!, organizationId)),
    enabled: pursuitId != null && organizacionResuelta(organizationId),
    staleTime: 30_000,
  });
}

/**
 * Invalidación común de las tres mutaciones.
 *
 * `pursuitKeys.all` es prefijo de la lista de tareas, del detalle, de las
 * métricas y de la agenda: una sola invalidación cubre todo lo que depende de
 * `next_action`, que el servidor acaba de recalcular.
 */
function invalidarTareas(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: pursuitKeys.all }),
    queryClient.invalidateQueries({ queryKey: organizationKeys.all }),
  ]);
}

/**
 * Las tres mutaciones reciben la oportunidad **en la mutación**, no en el hook.
 *
 * Es el mismo motivo que en `useMoverPursuit`: la agenda completa la tarea de
 * la fila activa, y cuál es no se sabe hasta que el usuario pulsa. Ligar el id
 * al hook obligaría a montar uno por fila.
 */
export function useCrearTarea() {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: ({ pursuitId, ...input }: PursuitTaskCreate & { pursuitId: number }) =>
      apiMutate<PursuitTask>("POST", rutaTareas(pursuitId, organizationId), input),
    onSuccess: () => invalidarTareas(queryClient),
  });
}

/**
 * Cambios sobre una tarea. `limpiar_*` viajan siempre en `false` salvo que se
 * pidan: el contrato usa `null` para «no tocar», así que sin esas dos banderas
 * no habría forma de distinguir «deja la fecha como está» de «quítasela».
 */
export function useActualizarTarea() {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: ({
      pursuitId,
      taskId,
      ...cambios
    }: Partial<PursuitTaskPatch> & { pursuitId: number; taskId: number }) =>
      apiMutate<PursuitTask>("PATCH", rutaTarea(pursuitId, taskId, organizationId), {
        limpiar_responsable: false,
        limpiar_vence: false,
        ...cambios,
      } satisfies PursuitTaskPatch),
    onSuccess: () => invalidarTareas(queryClient),
  });
}

export function useBorrarTarea() {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: ({ pursuitId, taskId }: { pursuitId: number; taskId: number }) =>
      apiMutate<void>("DELETE", rutaTarea(pursuitId, taskId, organizationId)),
    onSuccess: () => invalidarTareas(queryClient),
  });
}
