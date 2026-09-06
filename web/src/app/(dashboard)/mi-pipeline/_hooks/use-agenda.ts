"use client";

/**
 * Datos, selección y gestos de la agenda.
 *
 * El backend fusiona, ordena y clasifica (`GET /pursuits/agenda`); aquí solo
 * viven la fila activa, el teclado —mismo contrato que el Radar: J/K recorren,
 * S sigue/anticipa, X descarta, ⏎ abre— y las tres acciones que esos gestos
 * comparten con los botones de cada fila.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useFilters } from "@/lib/filters";
import { useOrganizationStore } from "@/hooks/use-organization";
import { useDismissRadarTender, useRestoreRadarTender } from "@/hooks/use-radar";
import {
  type PipelineAgendaItem,
  useCreatePursuit,
  usePipelineAgenda,
} from "@/hooks/use-pursuits";

export function useAgenda() {
  const router = useRouter();
  const filters = useFilters();
  const tecnologia = filters.tecnologias[0] ?? null;
  const ccaa = filters.ccaas[0] ?? null;

  const [soloMios, setSoloMios] = React.useState(false);
  const { data, isLoading, error, refetch } = usePipelineAgenda({ soloMios, tecnologia, ccaa });

  const createPursuit = useCreatePursuit();
  const dismissTender = useDismissRadarTender();
  const restoreTender = useRestoreRadarTender();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);

  const items = React.useMemo(() => data?.items ?? [], [data]);
  const [selected, setSelected] = React.useState(0);
  const activeIndex = Math.min(selected, Math.max(0, items.length - 1));
  const active: PipelineAgendaItem | undefined = items[activeIndex];

  const seguir = React.useCallback(
    async (item: PipelineAgendaItem) => {
      try {
        const pursuit = await createPursuit.mutateAsync({ licitacion_id: item.licitacion_id });
        setActiveOrganizationId(pursuit.organization_id);
        toast.success(
          item.kind === "renovacion" ? "Renovación anticipada como pursuit" : "Oportunidad abierta",
        );
        router.push(`/oportunidades/${pursuit.id}`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "No se pudo abrir la oportunidad");
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

  const abrir = React.useCallback(
    (item: PipelineAgendaItem) => {
      if (item.kind === "pursuit" && item.pursuit_id != null) {
        router.push(`/oportunidades/${item.pursuit_id}`);
        return;
      }
      void seguir(item);
    },
    [router, seguir],
  );

  // Teclado: mismo contrato que el Radar. Ignorado con el foco en un campo.
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!items.length) return;
      const key = event.key.toLowerCase();
      if (key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        setSelected((current) => Math.min(current + 1, items.length - 1));
      } else if (key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        setSelected((current) => Math.max(current - 1, 0));
      } else if (key === "s") {
        event.preventDefault();
        if (active && active.kind !== "pursuit") void seguir(active);
      } else if (key === "x") {
        event.preventDefault();
        if (active && active.kind === "senal") descartar(active);
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (active) abrir(active);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [abrir, active, descartar, items.length, seguir]);

  const alternarSoloMios = React.useCallback(() => {
    setSoloMios((value) => !value);
    setSelected(0);
  }, []);

  return {
    data,
    isLoading,
    error,
    refetch,
    items,
    activeIndex,
    active,
    setSelected,
    soloMios,
    alternarSoloMios,
    seguir,
    descartar,
    abrir,
    irAlRadar: () => router.push("/radar"),
  };
}

export type Agenda = ReturnType<typeof useAgenda>;
