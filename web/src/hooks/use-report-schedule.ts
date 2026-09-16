"use client";

/**
 * Programación del informe semanal de la organización (T6).
 *
 * Vive aparte de `use-organization-settings` porque el backend también los
 * separa: las familias tecnológicas están en `organizations.settings_json` y
 * esto en su propia tabla (`organization_report_schedules`, v132). El motivo no
 * es de estilo: el scheduler consulta la programación por día y hora en cada
 * pasada, y buscar dentro de un JSON de todas las organizaciones para saber a
 * quién le toca el lunes sería un escaneo completo cada cuatro horas.
 *
 * El GET devuelve valores por defecto cuando todavía no hay fila —lunes a las
 * 07:00, apagado— para que el formulario pueda enseñarlos en vez de un hueco.
 * No crea nada: quien sólo entra a mirar no deja programación escrita.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { organizationKeys } from "@/lib/query-keys";

export interface ReportSchedule {
  organization_id: number;
  tipo: string;
  activo: boolean;
  /** 0 = lunes, como `Date.getDay()` **no** lo hace. Ver `DIAS`. */
  dia_semana: number;
  hora_utc: number;
  destinatarios: string[] | null;
  ultimo_envio_at?: string | null;
  ultimo_estado?: string | null;
}

/**
 * Índice 0 = lunes, que es la numeración del backend (`datetime.weekday()`) y
 * la del `CHECK` de v132 — **no** la de `Date.getDay()`, donde 0 es domingo.
 * Se escribe una vez aquí para que ninguna pantalla la reinvente al revés.
 */
export const DIAS = [
  "lunes",
  "martes",
  "miércoles",
  "jueves",
  "viernes",
  "sábado",
  "domingo",
] as const;

export const reportScheduleKeys = {
  detail: (organizationId: number | null) =>
    [...organizationKeys.all, "report-schedule", organizationId] as const,
};

export function useReportSchedule(organizationId: number | null) {
  return useQuery({
    queryKey: reportScheduleKeys.detail(organizationId),
    queryFn: () =>
      fetchWithAuth<ReportSchedule>(
        `/api/v1/organizations/${organizationId}/report-schedule`,
      ),
    enabled: organizationId != null,
    staleTime: 60_000,
    // Un 403 aquí es lo normal para quien no es owner ni admin: la tarjeta se
    // esconde y no hay error que enseñar.
    retry: false,
    meta: { silent: true },
  });
}

export interface GuardarProgramacion {
  activo: boolean;
  dia_semana: number;
  hora_utc: number;
  destinatarios: string[] | null;
}

export function useGuardarReportSchedule(organizationId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (cambios: GuardarProgramacion) =>
      apiMutate<ReportSchedule>(
        "PUT",
        `/api/v1/organizations/${organizationId}/report-schedule`,
        cambios,
      ),
    onSuccess: (programacion) => {
      // La respuesta ES la fila guardada, con `ultimo_envio_at` incluido: se
      // escribe en caché en vez de invalidar para que el panel de diagnóstico
      // no parpadee a vacío entre el guardado y el refetch.
      queryClient.setQueryData(reportScheduleKeys.detail(organizationId), programacion);
    },
  });
}
