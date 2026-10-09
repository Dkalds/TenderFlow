"use client";

/**
 * Lo que se le puede **hacer** a una fila de la agenda: seguir, descartar o
 * posponer una señal; completar una tarea; apuntar la próxima acción de una
 * oportunidad; retirarla si su plazo pasó sin oferta; abrirla.
 *
 * Son las mismas acciones para el botón de la fila, el del inspector y el
 * atajo de teclado, así que viven aquí y no en cada uno. Qué fila está activa y
 * qué se está viendo es cosa de `use-agenda.ts`.
 *
 * Toda escritura se puede deshacer desde su aviso **salvo retirar**: `withdrawn`
 * es un estado terminal y la API no reabre, y por eso es la única que pasa por
 * un diálogo de confirmación (`porRetirar`).
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/query-feedback";
import { useOrganizationStore } from "@/hooks/use-organization";
import { useDismissRadarTender, useRestoreRadarTender } from "@/hooks/use-radar";
import { useActualizarTarea, useCrearTarea } from "@/hooks/use-pursuit-tasks";
import { type PipelineAgendaItem, useCreatePursuit, useMoverPursuit } from "@/hooks/use-pursuits";
import { DIAS_POSPONER } from "../_components/agenda/agenda-meta";
import { tituloDe } from "../_components/agenda/agenda-texto";

export function useAgendaAcciones() {
  const router = useRouter();
  const createPursuit = useCreatePursuit();
  const moverPursuit = useMoverPursuit();
  const dismissTender = useDismissRadarTender();
  const restoreTender = useRestoreRadarTender();
  const actualizarTarea = useActualizarTarea();
  const crearTarea = useCrearTarea();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);

  /** La oportunidad que espera confirmación para retirarse, si hay alguna. */
  const [porRetirar, setPorRetirar] = React.useState<PipelineAgendaItem | null>(null);

  const seguir = React.useCallback(
    async (item: PipelineAgendaItem) => {
      try {
        const pursuit = await createPursuit.mutateAsync({ licitacion_id: item.licitacion_id });
        setActiveOrganizationId(pursuit.organization_id);
        toast.success(
          item.kind === "renovacion" ? "Renovación anticipada como oportunidad" : "Oportunidad abierta",
        );
        router.push(`/oportunidades/${pursuit.id}`);
      } catch (err) {
        toast.error("No se pudo abrir la oportunidad", { description: getErrorMessage(err, "accion") });
      }
    },
    [createPursuit, router, setActiveOrganizationId],
  );

  const descartar = React.useCallback(
    (item: PipelineAgendaItem) => {
      dismissTender.mutate({ idExterno: item.licitacion_id });
      toast("Señal descartada", {
        description: item.titulo ?? undefined,
        action: { label: "Deshacer", onClick: () => restoreTender.mutate(item.licitacion_id) },
      });
    },
    [dismissTender, restoreTender],
  );

  /**
   * Posponer: el mismo triaje del Radar con caducidad (`accion: "posponer"`).
   * La señal vuelve sola pasada la semana, así que «ahora no» deja de ser
   * indistinguible de «nunca» — que es lo que era descartar.
   */
  const posponer = React.useCallback(
    (item: PipelineAgendaItem) => {
      dismissTender.mutate({
        idExterno: item.licitacion_id,
        accion: "posponer",
        dias: DIAS_POSPONER,
      });
      toast(`Señal pospuesta ${DIAS_POSPONER} días`, {
        description: item.titulo ?? undefined,
        action: { label: "Deshacer", onClick: () => restoreTender.mutate(item.licitacion_id) },
      });
    },
    [dismissTender, restoreTender],
  );

  /**
   * Completar la tarea de la fila. Siempre con deshacer: es la única acción de
   * escritura que el teclado dispara, y una tecla que cierra trabajo sin vuelta
   * atrás convierte un dedo torpe en una tarea perdida.
   */
  const completarTarea = React.useCallback(
    (item: PipelineAgendaItem) => {
      const pursuitId = item.pursuit_id;
      const taskId = item.tarea_id;
      if (pursuitId == null || taskId == null) return;
      actualizarTarea.mutate(
        { pursuitId, taskId, estado: "hecha" },
        {
          onSuccess: () =>
            toast.success("Tarea completada", {
              description: tituloDe(item),
              action: {
                label: "Deshacer",
                onClick: () =>
                  actualizarTarea.mutate({ pursuitId, taskId, estado: "pendiente" }),
              },
            }),
          onError: (err) =>
            toast.error("No se pudo completar la tarea", { description: getErrorMessage(err, "accion") }),
        },
      );
    },
    [actualizarTarea],
  );

  /**
   * Apuntar la próxima acción de una oportunidad que no tiene ninguna. Es una
   * **tarea**: la API deriva de ella `next_action`, así que la oportunidad deja
   * de contar en «Sin próxima acción» y la tarea gana su fila en la agenda.
   */
  const apuntarAccion = React.useCallback(
    (
      item: PipelineAgendaItem,
      accion: { titulo: string; vence: string | null },
      alGuardar?: () => void,
    ) => {
      if (item.pursuit_id == null) return;
      crearTarea.mutate(
        { pursuitId: item.pursuit_id, titulo: accion.titulo, vence: accion.vence },
        {
          onSuccess: () => {
            toast.success("Próxima acción apuntada", { description: accion.titulo });
            alGuardar?.();
          },
          onError: (err) =>
            toast.error("No se pudo apuntar la acción", { description: getErrorMessage(err, "accion") }),
        },
      );
    },
    [crearTarea],
  );

  /**
   * Retirar como no presentada la oportunidad que espera confirmación.
   *
   * El motivo va puesto —`no_presentada`— porque es lo que la acción afirma: el
   * plazo pasó y no hubo oferta.
   */
  const confirmarRetirada = React.useCallback(() => {
    const item = porRetirar;
    if (!item || item.pursuit_id == null || item.version == null) return;
    moverPursuit.mutate(
      {
        id: item.pursuit_id,
        status: "withdrawn",
        outcome: "cancelled",
        outcome_reason_code: "no_presentada",
        expected_version: item.version,
      },
      {
        onSuccess: () => {
          setPorRetirar(null);
          toast.success("Oportunidad retirada como no presentada", { description: tituloDe(item) });
        },
        onError: (err) =>
          toast.error("No se pudo retirar la oportunidad", { description: getErrorMessage(err, "accion") }),
      },
    );
  }, [moverPursuit, porRetirar]);

  const abrir = React.useCallback(
    (item: PipelineAgendaItem) => {
      if (item.kind === "senal") {
        void seguir(item);
        return;
      }
      const pursuitId =
        item.kind === "contrato" ? (item.renovacion_pursuit_id ?? item.pursuit_id) : item.pursuit_id;
      if (pursuitId != null) {
        router.push(`/oportunidades/${pursuitId}`);
        return;
      }
      void seguir(item);
    },
    [router, seguir],
  );

  return {
    seguir,
    descartar,
    posponer,
    completarTarea,
    apuntarAccion,
    apuntando: crearTarea.isPending,
    porRetirar,
    pedirRetirada: setPorRetirar,
    cancelarRetirada: () => setPorRetirar(null),
    confirmarRetirada,
    retirando: moverPursuit.isPending,
    abrir,
    verRenovacion: (pursuitId: number) => router.push(`/oportunidades/${pursuitId}`),
    irAlRadar: () => router.push("/radar"),
  };
}
