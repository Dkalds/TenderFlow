"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { type FiltroEtiqueta, useFiltroEtiqueta } from "@/components/etiquetas/filtro-etiqueta";
import { useCreatePursuit } from "@/hooks/use-pursuits";
import { useSeguimiento } from "@/hooks/use-seguimiento";
import { useOrganizationStore } from "@/hooks/use-organization";
import { useFilters } from "@/lib/filters";
import { getJSON, setJSON } from "@/lib/storage";
import {
  type AccionAplazar,
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
import type { SegmentKey, SortKey } from "./radar-segmentos";
import { type RadarProximasConsola, useRadarProximas } from "./use-radar-proximas";

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

export { SEGMENTS, SORTS, type SegmentKey, type SortKey } from "./radar-segmentos";

/** Marca de la última visita, para el punto «nueva» de cada fila. */
const LAST_VISIT_KEY = "radar-last-visit";

export interface RadarConsola {
  rows: RadarTender[];
  active: RadarTender | undefined;
  activeIndex: number;
  /**
   * `null` = todavía no se sabe. Un «0» mientras carga afirma que no hay nada,
   * que es justo lo que la bandeja «Próximas» no puede decir por defecto: su
   * caso normal es estar vacía y el usuario no podría distinguir «vacía» de
   * «aún no ha llegado».
   */
  counts: Record<SegmentKey, number | null>;
  /** Datos de la bandeja «Próximas» (T5), que no comparte forma con las demás. */
  proximas: RadarProximasConsola;
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
  aplazar: (tender: RadarTender, accion: AccionAplazar, dias: number) => void;
  restoreAll: () => void;
  toggleFollow: (tender: RadarTender) => void;
  /** Aviso con deshacer tras alternar desde `SeguirBoton`. */
  avisarSeguimiento: (tender: RadarTender, ahoraSigue: boolean) => void;
  openPursuit: (tender: RadarTender) => Promise<void>;
  /** F1.3 — anota que se leyó la explicación del score de esta señal. */
  marcarExplicacion: (tender: RadarTender) => void;
  /** F1.6 — filtro por etiqueta de favorito, sobre las filas ya cargadas. */
  etiqueta: FiltroEtiqueta;
}

export function useRadarConsola(): RadarConsola {
  const router = useRouter();
  const filters = useFilters();
  const tecnologia = filters.tecnologias[0] ?? null;
  const { data, isLoading, error, refetch } = useRadar(tecnologia);
  const { data: dismissedIds = [] } = useRadarDismissals();
  const dismissTender = useDismissRadarTender();
  const restoreTender = useRestoreRadarTender();

  // El mismo estado que pinta `SeguirBoton` en cada fila y en el inspector
  // (ADR-031 §C): el atajo «S» y el botón pasan por el mismo sitio.
  const seguimiento = useSeguimiento("licitacion");
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

  const followedIds = seguimiento.ids;

  const all = React.useMemo(() => data?.items ?? [], [data]);

  // El ranking llega ya sin las descartadas (`exclude_dismissed`), así que su
  // segmento se hidrata aparte y su contador es el total real, no la
  // intersección con un top-24 del que ya salieron.
  const descartadas = useRadarDismissedTenders(dismissedIds, segment === "descartadas");

  // «Próximas» sale de su propio endpoint (`/radar/proximas`): son estados sin
  // score ni plazo, así que no comparten ni el tipo ni el ranking con el resto
  // de segmentos. Su contador es el `total` del servidor sobre el corpus, no la
  // longitud de la página recibida.
  const proximas = useRadarProximas();
  // F1.6 — las etiquetas de un expediente son las de su favorito (`id_externo`).
  const idsVisibles = [...all, ...descartadas.items].map((t) => t.id_externo);
  const etiqueta = useFiltroEtiqueta("favorito", idsVisibles);
  const pasaEtiqueta = etiqueta.pasa;

  const counts = React.useMemo(
    () => ({
      bandeja: all.filter((t) => !dismissed.has(t.id_externo) && !followedIds.has(t.id_externo))
        .length,
      proximas: proximas.total,
      siguiendo: all.filter((t) => followedIds.has(t.id_externo)).length,
      descartadas: dismissedIds.length,
      todas: all.length,
    }),
    [all, dismissed, dismissedIds, followedIds, proximas.total],
  );

  const rows = React.useMemo(() => {
    // La bandeja «Próximas» la pinta `RadarProximas` con sus propias filas: no
    // hay `RadarTender` que devolver aquí, y fabricar uno vacío dejaría al
    // inspector enseñando la ficha de la señal anterior.
    if (segment === "proximas") return [];
    // El backend ya excluyó las descartadas; el filtro cliente cubre la ventana
    // entre la mutación optimista y el refetch del ranking.
    const base = segment === "descartadas" ? descartadas.items : all;
    const filtered = base.filter((tender) => {
      if (!pasaEtiqueta(tender.id_externo)) return false;
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
  }, [all, descartadas.items, segment, sort, dismissed, followedIds, pasaEtiqueta]);

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

  // F1.3 — señales cuya explicación se abrió; el triaje lo lleva como
  // `explicacion_abierta` (mide si acompaña a la decisión, no curiosidad).
  const explicaciones = React.useRef(new Set<string>());
  const marcarExplicacion = React.useCallback(
    (tender: RadarTender) => void explicaciones.current.add(tender.id_externo),
    [],
  );

  // Descartar, silenciar y posponer (F5.6) son el mismo POST con otra acción.
  // El score y la banda viajan con él: son los que el usuario tenía delante al
  // decidir, y no se pueden reconstruir después (revisión v93).
  const aplazar = React.useCallback(
    (tender: RadarTender, accion?: AccionAplazar, dias?: number) => {
      dismissTender.mutate({
        idExterno: tender.id_externo,
        score: tender.score,
        banda: esBandaConocida(tender.band) ? tender.band : null,
        ...(explicaciones.current.has(tender.id_externo) ? { explicacionAbierta: true } : {}),
        ...(accion ? { accion, dias } : {}),
      });
      const titulo = !accion
        ? "Señal descartada"
        : accion === "silenciar"
          ? `Silenciada ${dias} días`
          : `Te lo recordamos en ${dias} días`;
      toast(titulo, {
        description: tender.titulo ?? undefined,
        action: { label: "Deshacer", onClick: () => restore(tender.id_externo) },
      });
    },
    [dismissTender, restore],
  );
  const dismiss = React.useCallback((tender: RadarTender) => aplazar(tender), [aplazar]);

  const { seguir, dejar, alternar } = seguimiento;

  /**
   * Aviso con «Deshacer» tras seguir o dejar de seguir (`SeguirBoton` y atajo
   * «S»). Deshacer es `seguir`/`dejar` explícito: alternar desde el toast
   * leería un estado ya cambiado. */
  const avisarSeguimiento = React.useCallback(
    (tender: RadarTender, ahoraSigue: boolean) => {
      const id = tender.id_externo;
      if (ahoraSigue) {
        toast("Añadida a seguimiento", {
          description: tender.titulo,
          action: { label: "Deshacer", onClick: () => dejar(id) },
        });
      } else {
        toast("Dejaste de seguir", {
          description: tender.titulo,
          action: { label: "Deshacer", onClick: () => seguir(id) },
        });
      }
    },
    [seguir, dejar],
  );

  const toggleFollow = React.useCallback(
    (tender: RadarTender) => avisarSeguimiento(tender, alternar(tender.id_externo)),
    [alternar, avisarSeguimiento],
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
    proximas,
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
    aplazar,
    restoreAll,
    toggleFollow,
    avisarSeguimiento,
    openPursuit,
    marcarExplicacion,
    etiqueta,
  };
}
