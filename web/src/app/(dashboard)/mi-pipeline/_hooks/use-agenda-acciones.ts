"use client";

/**
 * Lo que se le puede **hacer** a una fila de la agenda: seguir, descartar o
 * posponer una señal; completar una tarea; decidir el GO/NO-GO de una
 * oportunidad, apuntar su próxima acción o retirarla si ya no admite oferta;
 * poner la fecha de fin de un contrato; abrirla.
 *
 * Son las mismas acciones para el botón de la fila, el del inspector y el
 * atajo de teclado, así que viven aquí y no en cada uno. Qué fila está activa y
 * qué se está viendo es cosa de `use-agenda.ts`.
 *
 * Toda escritura se puede deshacer desde su aviso **salvo las que cierran una
 * oportunidad** —retirarla y el NO-GO—: `withdrawn` es un estado terminal y la
 * API no reabre. Retirar pasa por un diálogo de confirmación y tiene su propio
 * hook (`use-agenda-retirada.ts`); el NO-GO lo avisa en su propia capa, antes
 * de guardar.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ApiError } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/query-feedback";
import { cambioDeDecision, type Decision } from "@/components/pursuits/decidir-go-no-go";
import { decisionLabel } from "@/components/pursuits/pursuit-presenters";
import { useFijarFechaFin } from "@/hooks/use-cartera";
import { useOrganizationStore } from "@/hooks/use-organization";
import { useDismissRadarTender, useRestoreRadarTender } from "@/hooks/use-radar";
import { useActualizarTarea, useCrearTarea } from "@/hooks/use-pursuit-tasks";
import { type PipelineAgendaItem, useCreatePursuit, useMoverPursuit } from "@/hooks/use-pursuits";
import { DIAS_POSPONER } from "../_components/agenda/agenda-meta";
import { tituloDe } from "../_components/agenda/agenda-texto";
import { useAgendaRetirada } from "./use-agenda-retirada";

export function useAgendaAcciones() {
  const router = useRouter();
  const createPursuit = useCreatePursuit();
  const moverPursuit = useMoverPursuit();
  const dismissTender = useDismissRadarTender();
  const restoreTender = useRestoreRadarTender();
  const actualizarTarea = useActualizarTarea();
  const crearTarea = useCrearTarea();
  const fechaFin = useFijarFechaFin();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);
  const retirada = useAgendaRetirada();

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
   * Decidir el GO/NO-GO desde la fila. Un solo cambio registra la decisión y
   * mueve la oportunidad con ella: el GO a «Preparando oferta» —la API deja
   * saltar las fases previas cuando hay GO— y el NO-GO a retirada.
   */
  const decidir = React.useCallback(
    (item: PipelineAgendaItem, decision: Decision, alGuardar?: () => void) => {
      if (item.pursuit_id == null || item.version == null) return;
      moverPursuit.mutate(
        { id: item.pursuit_id, ...cambioDeDecision(decision, item.version) },
        {
          onSuccess: () => {
            toast.success(
              decision.decision === "go"
                ? `Decisión ${decisionLabel("go")}: pasa a preparar la oferta`
                : `Decisión ${decisionLabel("no_go")}: oportunidad retirada`,
              { description: tituloDe(item) },
            );
            alGuardar?.();
          },
          onError: (err) =>
            toast.error(
              err instanceof ApiError && err.status === 409
                ? "Alguien del equipo la cambió mientras decidías"
                : "No se pudo guardar la decisión",
              { description: getErrorMessage(err, "accion") },
            ),
        },
      );
    },
    [moverPursuit],
  );

  /** Poner o corregir la fecha de fin de un contrato de la cartera. */
  const fijarFechaFin = React.useCallback(
    (item: PipelineAgendaItem, fecha: string, alGuardar?: () => void) => {
      if (item.cartera_id == null) return;
      fechaFin.mutate(
        { carteraId: item.cartera_id, fechaFin: fecha },
        {
          onSuccess: () => {
            toast.success("Fecha de fin guardada", { description: tituloDe(item) });
            alGuardar?.();
          },
          onError: (err) =>
            toast.error("No se pudo guardar la fecha de fin", {
              description: getErrorMessage(err, "accion"),
            }),
        },
      );
    },
    [fechaFin],
  );

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
    decidir,
    decidiendo: moverPursuit.isPending,
    ...retirada,
    fijarFechaFin,
    guardandoFechaFin: fechaFin.isPending,
    abrir,
    verRenovacion: (pursuitId: number) => router.push(`/oportunidades/${pursuitId}`),
    irAlRadar: () => router.push("/radar"),
  };
}
