"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useCreatePursuit } from "@/hooks/use-pursuits";
import {
  useAddWatchlistItem,
  useRemoveWatchlistItem,
  useWatchlistItems,
} from "@/hooks/use-watchlist-items";
import { useOrganizationStore } from "@/hooks/use-organization";
import { useFilters } from "@/lib/filters";
import { getJSON, setJSON } from "@/lib/storage";
import {
  type RadarTender,
  type ScoringSignals,
  esBandaConocida,
  useDismissRadarTender,
  useRadar,
  useRadarDismissals,
  useRadarDismissedTenders,
  useRestoreRadarTender,
} from "@/hooks/use-radar";
import { daysLeft } from "../_components/radar-shared";

/**
 * Estado y acciones de la consola del Radar, fuera del árbol de render.
 *
 * Aquí vive todo lo que la pantalla *hace*: qué bandeja se está mirando, en qué
 * orden, sobre qué fila se actúa, y las tres escrituras que el Radar dispara
 * (seguir, descartar, abrir oportunidad). Los componentes de `_components/`
 * reciben ya el resultado y no vuelven a consultar nada.
 *
 * El hook no habla con la red por su cuenta: usa los hooks de datos de
 * `@/hooks/use-radar`, que son los que consumen la API por HTTP (invariante §3.8).
 */

export const SEGMENTS = [
  { key: "bandeja", label: "Bandeja" },
  { key: "siguiendo", label: "Siguiendo" },
  { key: "descartadas", label: "Descartadas" },
  { key: "todas", label: "Todas" },
] as const;

export const SORTS = [
  { key: "score", label: "Score" },
  { key: "plazo", label: "Plazo" },
  { key: "importe", label: "Importe" },
] as const;

export type SegmentKey = (typeof SEGMENTS)[number]["key"];
export type SortKey = (typeof SORTS)[number]["key"];

/** Marca de la última visita, para el punto «nueva» de cada fila. */
const LAST_VISIT_KEY = "radar-last-visit";

export interface RadarConsola {
  rows: RadarTender[];
  active: RadarTender | undefined;
  activeIndex: number;
  counts: Record<SegmentKey, number>;
  signals: ScoringSignals | null | undefined;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
  segment: SegmentKey;
  setSegment: (segment: SegmentKey) => void;
  sort: SortKey;
  setSort: (sort: SortKey) => void;
  selected: number;
  setSelected: React.Dispatch<React.SetStateAction<number>>;
  dismissedCount: number;
  followedIds: Set<string>;
  lastVisit: number;
  opening: boolean;
  dismiss: (tender: RadarTender) => void;
  restoreAll: () => void;
  toggleFollow: (tender: RadarTender) => void;
  openPursuit: (tender: RadarTender) => Promise<void>;
}

export function useRadarConsola(): RadarConsola {
  const router = useRouter();
  const filters = useFilters();
  const tecnologia = filters.tecnologias[0] ?? null;
  const { data, isLoading, error, refetch } = useRadar(tecnologia);
  const { data: dismissedIds = [] } = useRadarDismissals();
  const dismissTender = useDismissRadarTender();
  const restoreTender = useRestoreRadarTender();

  const { data: watched = [] } = useWatchlistItems();
  const addWatchlist = useAddWatchlistItem();
  const removeWatchlist = useRemoveWatchlistItem();
  const createPursuit = useCreatePursuit();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);

  const [segment, setSegmentState] = React.useState<SegmentKey>("bandeja");
  const [sort, setSort] = React.useState<SortKey>("score");
  const [selected, setSelected] = React.useState(0);
  // El descarte es server-side (`/api/v1/radar/dismissals`): recargar
  // conserva el triaje. Antes vivía en `useState` y se perdía al recargar.
  const dismissed = React.useMemo(() => new Set(dismissedIds), [dismissedIds]);

  // «Nueva» = publicada después de la última vez que se abrió el Radar. El
  // sello se lee una vez al montar y se reescribe al salir, así que la marca
  // sobrevive a la sesión y no se apaga mientras estás mirando la lista.
  const [lastVisit] = React.useState<number>(() => getJSON<number>(LAST_VISIT_KEY, 0));
  React.useEffect(() => {
    return () => {
      setJSON(LAST_VISIT_KEY, Date.now());
    };
  }, []);

  const followedIds = React.useMemo(
    () => new Set(watched.map((item) => item.id_externo)),
    [watched],
  );

  const all = React.useMemo(() => data?.items ?? [], [data]);

  // El ranking llega ya sin las descartadas (`exclude_dismissed`), así que su
  // segmento se hidrata aparte y su contador es el total real, no la
  // intersección con un top-24 del que ya salieron.
  const descartadas = useRadarDismissedTenders(dismissedIds, segment === "descartadas");

  const counts = React.useMemo(
    () => ({
      bandeja: all.filter((t) => !dismissed.has(t.id_externo) && !followedIds.has(t.id_externo))
        .length,
      siguiendo: all.filter((t) => followedIds.has(t.id_externo)).length,
      descartadas: dismissedIds.length,
      todas: all.length,
    }),
    [all, dismissed, dismissedIds, followedIds],
  );

  const rows = React.useMemo(() => {
    // El backend ya excluyó las descartadas; el filtro cliente cubre la ventana
    // entre la mutación optimista y el refetch del ranking.
    const base = segment === "descartadas" ? descartadas.items : all;
    const filtered = base.filter((tender) => {
      if (segment === "bandeja")
        return !dismissed.has(tender.id_externo) && !followedIds.has(tender.id_externo);
      if (segment === "siguiendo") return followedIds.has(tender.id_externo);
      if (segment === "descartadas") return true;
      return !dismissed.has(tender.id_externo);
    });
    return filtered.slice().sort((a, b) => {
      if (sort === "score") return (b.score ?? -1) - (a.score ?? -1);
      if (sort === "plazo")
        return (daysLeft(a.fecha_limite) ?? 9999) - (daysLeft(b.fecha_limite) ?? 9999);
      return (b.importe ?? 0) - (a.importe ?? 0);
    });
  }, [all, descartadas.items, segment, sort, dismissed, followedIds]);

  const activeIndex = Math.min(selected, Math.max(0, rows.length - 1));
  const active: RadarTender | undefined = rows[activeIndex];

  const setSegment = React.useCallback((next: SegmentKey) => {
    setSegmentState(next);
    setSelected(0);
  }, []);

  const restore = React.useCallback(
    (id: string) => {
      restoreTender.mutate(id);
    },
    [restoreTender],
  );

  const restoreAll = React.useCallback(
    () => dismissed.forEach((id) => restore(id)),
    [dismissed, restore],
  );

  const dismiss = React.useCallback(
    (tender: RadarTender) => {
      // El score y la banda viajan con el descarte: son los que el usuario tenía
      // delante al decidir, y no se pueden reconstruir después (revisión v93).
      dismissTender.mutate({
        idExterno: tender.id_externo,
        score: tender.score,
        banda: esBandaConocida(tender.band) ? tender.band : null,
      });
      toast("Señal descartada", {
        description: tender.titulo ?? undefined,
        action: { label: "Deshacer", onClick: () => restore(tender.id_externo) },
      });
    },
    [dismissTender, restore],
  );

  const toggleFollow = React.useCallback(
    (tender: RadarTender) => {
      const id = tender.id_externo;
      if (followedIds.has(id)) {
        removeWatchlist.mutate(id);
        toast("Dejaste de seguir", {
          description: tender.titulo,
          action: { label: "Deshacer", onClick: () => addWatchlist.mutate(id) },
        });
      } else {
        addWatchlist.mutate(id);
        toast("Añadida a seguimiento", {
          description: tender.titulo,
          action: { label: "Deshacer", onClick: () => removeWatchlist.mutate(id) },
        });
      }
    },
    [addWatchlist, followedIds, removeWatchlist],
  );

  const openPursuit = React.useCallback(
    async (tender: RadarTender) => {
      try {
        const pursuit = await createPursuit.mutateAsync({
          licitacion_id: tender.id_externo,
          // Mismo motivo que en el descarte: sella la puntuación que motivó
          // abrir la oportunidad, para poder medir el win rate por banda.
          score_al_abrir: tender.score,
          banda_al_abrir: esBandaConocida(tender.band) ? tender.band : null,
        });
        setActiveOrganizationId(pursuit.organization_id);
        toast.success("Oportunidad abierta para el equipo");
        router.push(`/oportunidades/${pursuit.id}`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "No se pudo abrir la oportunidad");
      }
    },
    [createPursuit, router, setActiveOrganizationId],
  );

  return {
    rows,
    active,
    activeIndex,
    counts,
    signals: data?.signals,
    isLoading,
    error,
    refetch,
    segment,
    setSegment,
    sort,
    setSort,
    selected,
    setSelected,
    dismissedCount: dismissed.size,
    followedIds,
    lastVisit,
    opening: createPursuit.isPending,
    dismiss,
    restoreAll,
    toggleFollow,
    openPursuit,
  };
}
