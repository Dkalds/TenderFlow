"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { RadioTower, Star, X } from "lucide-react";
import { toast } from "sonner";
import { useCreatePursuit } from "@/hooks/use-pursuits";
import {
  useAddWatchlistItem,
  useRemoveWatchlistItem,
  useWatchlistItems,
} from "@/hooks/use-watchlist-items";
import { useOrganizationStore } from "@/hooks/use-organization";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScoreDesglose } from "@/components/score-desglose";
import { useFilters } from "@/lib/filters";
import { useDensity } from "@/lib/density";
import { getJSON, setJSON } from "@/lib/storage";
import { cn, formatNumber } from "@/lib/utils";
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
import { RadarInspector } from "./_components/radar-inspector";
import { bandColor, daysLeft, shortEur, urgency } from "./_components/radar-shared";

/**
 * Radar — consola de decisión diaria.
 *
 * El patrón: una superficie tabular densa, el detalle en el mismo plano y el
 * triaje sin cambiar de pantalla. Antes eran tarjetas de 140px de alto con
 * cuatro botones cada una: seis señales por pantalla y ninguna forma de
 * compararlas. Ahora caben catorce, se recorren con J/K, y seguir (S) o
 * descartar (X) no mueve nada más que la fila.
 *
 * Alcance real de la lista (`hooks/use-radar.ts`): es el **top-24 por potencial
 * comercial de todo el corpus abierto**, calculado en backend
 * (`GET /analytics/scoring?limit=24`). Hasta que `ScoredOpportunity` incluyó
 * `fecha_limite` y `tecnologia` esto no se podía consumir, y la lista eran las
 * 24 abiertas más recientes reordenadas por score — una ventana cronológica
 * presentada como priorización de mercado. Los expedientes resueltos,
 * adjudicados o anulados no entran: el Radar es una bandeja de decisión y
 * sobre ellos no hay decisión que tomar.
 *
 * El triaje (descartar / deshacer) es server-side: recargar lo conserva.
 *
 * **Por debajo de `md` esto deja de ser una tabla.** Las siete columnas miden
 * 666 px de ancho mínimo: a 375 px la acción quedaba a dos pantallazos de
 * scroll horizontal del título, y el caso de uso móvil real —un comercial
 * mirando el Radar en una visita— es justo decidir en cinco segundos. La
 * conversión no duplica el árbol: los mismos nodos se agrupan en envoltorios
 * que a partir de `md` se disuelven con `display: contents` y vuelven a caer
 * en sus columnas. Una sola fuente de datos, de lógica y de marcado.
 */

/**
 * Rejilla de la tabla — solo a partir de `md`. Por debajo no hay rejilla: la
 * fila es una ficha en columna (ver `rows.map`), y la cabecera de columnas
 * desaparece porque no habría columnas que rotular.
 */
const GRID = "md:grid-cols-[46px_1fr_176px_132px_108px_96px_108px] md:gap-3 md:px-3.5";
const SEGMENTS = [
  { key: "bandeja", label: "Bandeja" },
  { key: "siguiendo", label: "Siguiendo" },
  { key: "descartadas", label: "Descartadas" },
  { key: "todas", label: "Todas" },
] as const;
const SORTS = [
  { key: "score", label: "Score" },
  { key: "plazo", label: "Plazo" },
  { key: "importe", label: "Importe" },
] as const;
const SHORTCUTS = [
  { key: "J K", label: "navegar" },
  { key: "S", label: "seguir" },
  { key: "X", label: "descartar" },
  { key: "⏎", label: "abrir" },
];

type SegmentKey = (typeof SEGMENTS)[number]["key"];
type SortKey = (typeof SORTS)[number]["key"];

/**
 * Qué se le dice al usuario cuando el backend avisa de que el score va cojo.
 *
 * No es decoración: una señal caída puntúa igual que una sin datos —todas las
 * filas neutrales en esa dimensión— y el ranking sigue pareciendo sano. La
 * señal de margen estuvo muerta semanas por ese motivo. El texto describe la
 * consecuencia para quien decide, no el fallo técnico.
 */
const SIGNAL_WARNINGS: Record<string, string> = {
  competencia: "sin histórico de competencia: esa dimensión puntúa neutra",
  margen: "sin predicción de baja: esa dimensión puntúa neutra",
  percentiles: "el importe se compara contra el histórico completo, no contra el mercado abierto",
};

function signalWarnings(signals: ScoringSignals | null | undefined): string[] {
  if (!signals) return [];
  const avisos: string[] = [];
  if (signals.competencia !== "ok") avisos.push(SIGNAL_WARNINGS.competencia);
  if (signals.margen !== "ok") avisos.push(SIGNAL_WARNINGS.margen);
  if (signals.percentiles_fuente !== "universo_vivo") avisos.push(SIGNAL_WARNINGS.percentiles);
  return avisos;
}

/** Marca de la última visita, para el punto «nueva» de cada fila. */
const LAST_VISIT_KEY = "radar-last-visit";

/**
 * Controles que ya hacen algo propio con Intro. El atajo global se aparta ante
 * ellos porque escucha en `window`: sin este filtro, pulsar Intro con el foco
 * en «Restaurar», en un segmento o en el propio botón de una fila hacía
 * `preventDefault()` —cancelando ese botón— y abría una oportunidad sobre la
 * fila *seleccionada*, que no tiene por qué ser la que se está mirando.
 *
 * Las filas entran aquí por su `role="button"`: su Intro lo resuelve el
 * `onKeyDown` de la fila, que sí sabe sobre qué índice está actuando.
 */
const CONTROLES_CON_INTRO_PROPIO = 'a, button, select, [role="button"]';

/**
 * A partir de `md` el Radar es una tabla y las acciones de las filas inactivas
 * se ocultan (`md:opacity-0`). Eso las saca de la vista pero **no** del orden de
 * tabulación, así que hacía falta saber en JS si estamos en ese ancho: `inert`
 * es un atributo, no una clase, y no se puede condicionar con un prefijo
 * responsive. Por debajo de `md` el bloque es visible por decisión escrita
 * (ver el comentario de `radar-acciones`) y ahí no se inertiza nada.
 */
const CONSULTA_TABLA = "(min-width: 768px)";

function useAnchoDeTabla(): boolean {
  return React.useSyncExternalStore(
    (alCambiar) => {
      const consulta = window.matchMedia(CONSULTA_TABLA);
      consulta.addEventListener("change", alCambiar);
      return () => consulta.removeEventListener("change", alCambiar);
    },
    () => window.matchMedia(CONSULTA_TABLA).matches,
    // En servidor se asume la ficha móvil: el peor fallo posible es dejar
    // enfocable algo que ya lo era, nunca robar el foco a un botón visible.
    () => false,
  );
}

export default function RadarPage() {
  const router = useRouter();
  const filters = useFilters();
  const compact = useDensity((s) => s.compact);
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

  const enTabla = useAnchoDeTabla();
  const [segment, setSegment] = React.useState<SegmentKey>("bandeja");
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
  const avisosDeSenal = React.useMemo(() => signalWarnings(data?.signals), [data]);

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
      if (sort === "plazo") return (daysLeft(a.fecha_limite) ?? 9999) - (daysLeft(b.fecha_limite) ?? 9999);
      return (b.importe ?? 0) - (a.importe ?? 0);
    });
  }, [all, descartadas.items, segment, sort, dismissed, followedIds]);

  const activeIndex = Math.min(selected, Math.max(0, rows.length - 1));
  const active: RadarTender | undefined = rows[activeIndex];

  const restore = React.useCallback(
    (id: string) => {
      restoreTender.mutate(id);
    },
    [restoreTender],
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

  // Teclado: J/K (o flechas) recorren, S sigue, X descarta, ⏎ abre. Se ignora
  // mientras el foco está en un campo de texto, para no secuestrar la escritura,
  // y —en el caso de Intro— también ante cualquier control que ya tenga su
  // propia acción: abrir una oportunidad escribe en el backend y navega, así que
  // no puede dispararse como efecto colateral de pulsar otro botón.
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!rows.length) return;
      const key = event.key.toLowerCase();
      if (key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        setSelected((current) => Math.min(current + 1, rows.length - 1));
      } else if (key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        setSelected((current) => Math.max(current - 1, 0));
      } else if (key === "s") {
        event.preventDefault();
        if (active) toggleFollow(active);
      } else if (key === "x") {
        event.preventDefault();
        if (active) dismiss(active);
      } else if (event.key === "Enter") {
        if (target?.closest(CONTROLES_CON_INTRO_PROPIO)) return;
        event.preventDefault();
        if (active) void openPursuit(active);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, dismiss, openPursuit, rows.length, toggleFollow]);

  // La fila seleccionada se mantiene a la vista al navegar con teclado.
  const listRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    node?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const rowHeight = compact ? 44 : 56;
  const showEmpty = !isLoading && !error && rows.length === 0;

  const statusLine = isLoading
    ? "Cargando ámbito…"
    : error
      ? "Sin conexión con la API"
      : `${formatNumber(rows.length)} filas · ${counts.bandeja} por revisar · ${counts.siguiendo} en seguimiento`;

  return (
    <div className="flex h-[calc(100vh-52px)] min-h-0">
      {/* El borde derecho solo separa de algo cuando el inspector existe. */}
      <section className="flex min-w-0 flex-1 flex-col xl:border-r xl:border-border/70">
        {/* Segmentos y orden. En móvil envuelve en varias líneas en vez de
            desbordar: son ocho controles y ninguno se puede esconder sin
            quitarle al usuario el cambio de bandeja o el criterio de orden. */}
        <div className="flex min-h-11 flex-none flex-wrap items-center gap-x-0.5 gap-y-1.5 border-b border-border/60 px-3 py-2 md:h-11 md:flex-nowrap md:px-3.5 md:py-0">
          {SEGMENTS.map((item) => {
            const on = segment === item.key;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => {
                  setSegment(item.key);
                  setSelected(0);
                }}
                aria-pressed={on}
                className={cn(
                  // 32 px de alto en móvil: es un control que se pulsa con el
                  // pulgar, y 28 px queda justo por encima del mínimo de
                  // WCAG 2.5.8 pero se falla igual.
                  "tf-pressable inline-flex h-8 flex-none items-center gap-[7px] rounded-md border px-2.5 text-[12.5px] font-medium transition-colors duration-150 ease-out md:h-7",
                  on
                    ? "border-border/70 bg-secondary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {item.label}
                <span
                  className={cn(
                    "tf-tnum rounded px-1.5 py-0.5 font-mono text-[10px] font-medium",
                    on ? "bg-primary/16 text-primary" : "bg-muted-foreground/12 text-muted-foreground",
                  )}
                >
                  {counts[item.key]}
                </span>
              </button>
            );
          })}
          {/* En móvil el hueco es un salto de línea: los segmentos ocupan la
              primera y el orden la segunda. A partir de `md` vuelve a ser el
              muelle que empuja el orden al extremo derecho. */}
          <div className="basis-full md:flex-1" />
          {dismissed.size > 0 && (
            <button
              type="button"
              onClick={() => dismissed.forEach((id) => restore(id))}
              className="tf-pressable mr-1.5 h-7 flex-none rounded-md border border-border/70 px-2 text-[11px] font-medium text-muted-foreground transition-colors duration-140 ease-out hover:text-foreground md:h-6"
            >
              Restaurar {dismissed.size} descartada{dismissed.size === 1 ? "" : "s"}
            </button>
          )}
          <span className="mr-1.5 flex-none font-mono text-[8.5px] font-semibold uppercase tracking-[0.11em] text-muted-foreground/70">
            Orden
          </span>
          {SORTS.map((item) => {
            const on = sort === item.key;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => setSort(item.key)}
                aria-pressed={on}
                className={cn(
                  "tf-pressable h-7 flex-none rounded-md border px-2 text-[11px] font-medium transition-colors duration-150 ease-out md:h-6",
                  on
                    ? "border-primary/25 bg-primary/10 text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {item.label}
              </button>
            );
          })}
        </div>

        {avisosDeSenal.length > 0 && (
          <div
            role="status"
            className="flex-none border-b border-amber-500/25 bg-amber-500/8 px-3 py-1.5 text-[11.5px] leading-[1.45] text-amber-700 dark:text-amber-300 md:px-3.5"
          >
            <span className="font-medium">Score degradado</span> — {avisosDeSenal.join(" · ")}.
          </div>
        )}

        {/* Cabecera de columnas. Decisión escrita: por debajo de `md` no se
            renderiza porque no hay columnas que rotular — en la ficha cada
            dato lleva su propia forma (color de banda, «d» del plazo, «€» del
            importe) y un rótulo por celda sería ruido, no ayuda. */}
        <div
          data-slot="radar-cabecera"
          className={cn(
            "hidden h-[30px] flex-none items-center border-b border-border/70 bg-card/50 font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground md:grid",
            GRID,
          )}
        >
          <span>Score</span>
          <span>Licitación</span>
          <span>Órgano</span>
          <span>Tecnología</span>
          <span className="text-right">Importe</span>
          <span className="text-right">Plazo</span>
          <span className="text-right">Acción</span>
        </div>

        <div data-slot="radar-lista" ref={listRef} className="min-h-0 flex-1 overflow-y-auto">
          {error ? (
            <div
              role="alert"
              className="mx-auto my-10 max-w-[560px] rounded-xl border border-destructive/40 bg-destructive/8 px-6 py-5"
            >
              <div className="mb-2 flex items-center gap-2.5">
                <span className="grid h-5.5 w-5.5 flex-none place-items-center rounded-full border border-destructive/50 text-[12px] font-semibold text-destructive">
                  !
                </span>
                <span className="text-[13.5px] font-semibold text-destructive">
                  Error al cargar la bandeja del radar
                </span>
              </div>
              <p className="mb-3.5 font-mono text-xs leading-[1.55] text-destructive/80">
                {(error as Error).message}
              </p>
              <button
                type="button"
                onClick={() => void refetch()}
                className="tf-pressable h-[30px] rounded-md border border-border/80 px-3 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                ↻ Reintentar
              </button>
            </div>
          ) : isLoading ? (
            <div className="flex flex-col gap-2.5 p-3.5">
              {Array.from({ length: 9 }, (_, index) => (
                <span
                  key={index}
                  className="tf-shimmer block h-11 rounded-lg"
                  style={{ opacity: 1 - index * 0.07 }}
                />
              ))}
            </div>
          ) : showEmpty ? (
            <div className="px-5 py-20 text-center">
              <RadioTower
                className="mx-auto mb-3 h-6 w-6 text-muted-foreground/60"
                aria-hidden="true"
              />
              <div className="mb-1.5 font-display text-[15px] font-semibold leading-[1.3]">
                Bandeja al día
              </div>
              <p className="text-[13px] leading-[1.5] text-muted-foreground">
                No quedan señales con el ámbito actual.
              </p>
            </div>
          ) : (
            rows.map((tender, index) => {
              const isActive = index === activeIndex;
              const days = daysLeft(tender.fecha_limite);
              const urg = urgency(days);
              const isFollowed = followedIds.has(tender.id_externo);
              const publicado = tender.fecha_publicacion
                ? new Date(tender.fecha_publicacion).getTime()
                : 0;
              const isNew = lastVisit > 0 && publicado > lastVisit;
              const tech = tender.tecnologia ?? tender.ml_tech_principal ?? null;

              return (
                <div
                  key={tender.id_externo}
                  data-active={isActive}
                  role="button"
                  tabIndex={0}
                  aria-current={isActive ? "true" : undefined}
                  onClick={() => setSelected(index)}
                  // Tabular movía el foco sin mover la selección, así que el
                  // inspector, la banda lateral y los atajos globales seguían
                  // hablando de otra fila. Foco y selección son la misma cosa:
                  // lo que estás mirando es sobre lo que actúas.
                  onFocus={() => setSelected(index)}
                  onKeyDown={(event) => {
                    // Solo la tecla que llega a la fila, no la que sube desde
                    // sus botones: Intro sobre «Descartar» ya descarta, y
                    // dejarla pasar aquí abriría además la oportunidad.
                    if (event.target !== event.currentTarget) return;
                    if (event.key === " ") {
                      event.preventDefault();
                      setSelected(index);
                    } else if (event.key === "Enter") {
                      // Intro sobre la fila lo resuelve la fila, con su propio
                      // `index`: el listener de `window` trabaja sobre `active`
                      // y abría un pursuit —escritura en backend y navegación—
                      // sobre la fila seleccionada, no sobre la enfocada.
                      event.preventDefault();
                      setSelected(index);
                      void openPursuit(tender);
                    }
                  }}
                  // El alto fijo de fila es de la tabla: en la ficha el título
                  // ocupa dos líneas y recortarla a 44 px la dejaría sin nada.
                  style={{ "--tf-radar-fila": `${rowHeight}px` } as React.CSSProperties}
                  className={cn(
                    "relative flex cursor-pointer flex-col gap-2 border-b border-border/40 px-3 py-3 transition-colors duration-110 ease-out",
                    "md:grid md:h-[var(--tf-radar-fila)] md:items-center md:py-0",
                    GRID,
                    isActive ? "bg-primary/9" : "hover:bg-primary/5",
                  )}
                >
                  <span
                    aria-hidden="true"
                    className="absolute inset-y-0 left-0 w-0.5 transition-colors duration-110 ease-out"
                    style={{ background: isActive ? bandColor(tender.band) : "transparent" }}
                  />

                  {/* Los cuatro envoltorios que siguen agrupan la ficha móvil y
                      se disuelven con `md:contents`: a partir de `md` sus hijos
                      caen directos en la rejilla, en el mismo orden que rotula
                      la cabecera. Es lo que permite que ficha y fila sean el
                      mismo árbol y no puedan divergir. */}
                  <div className="flex min-w-0 items-center gap-3 md:contents">
                    {/* El score abre su propio desglose. Es un `Popover` y no
                        un `title` nativo por dos razones: el `title` no se
                        dispara con teclado y aquí el contenido no es una
                        etiqueta sino datos. El `stopPropagation` evita que
                        abrir la explicación cuente como seleccionar la fila. */}
                    <Popover>
                      <PopoverTrigger asChild>
                        <button
                          type="button"
                          data-slot="radar-score"
                          onClick={(e) => e.stopPropagation()}
                          aria-label={
                            tender.score != null
                              ? `Ver de qué está hecha la puntuación ${Math.round(tender.score)}`
                              : "Este expediente no está puntuado"
                          }
                          className="focus-visible:ring-ring flex flex-none cursor-pointer flex-col items-start gap-0.5 rounded-sm focus-visible:ring-2 focus-visible:outline-none"
                        >
                          <span
                            className="tf-tnum font-mono text-[15px] font-semibold leading-none"
                            style={{ color: bandColor(tender.band) }}
                          >
                            {tender.score != null ? Math.round(tender.score) : "—"}
                          </span>
                          {/* "s/p" era un código que nadie fuera del equipo
                              podía descifrar, en mono de 8 px. */}
                          <span className="text-muted-foreground font-mono text-[8px] font-medium uppercase leading-none tracking-[0.04em]">
                            {tender.band ?? "sin puntuar"}
                          </span>
                        </button>
                      </PopoverTrigger>
                      <PopoverContent
                        align="start"
                        className="w-[300px]"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <p className="mb-2.5 text-[11.5px] font-semibold">
                          Cómo se compone esta puntuación
                        </p>
                        <ScoreDesglose desglose={tender.desglose} riesgos={tender.risk_flags} />
                        <p className="text-muted-foreground mt-2.5 text-[10.5px] leading-relaxed">
                          Ordena el Radar sobre el corpus abierto. No es una
                          recomendación comercial: mide encaje con tu perfil, no
                          probabilidad de ganar.
                        </p>
                      </PopoverContent>
                    </Popover>

                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-center gap-[7px]">
                        {isNew && (
                          <span className="flex-none rounded border border-[hsl(var(--success)/0.3)] bg-[hsl(var(--success)/0.12)] px-1 py-0.5 font-mono text-[8px] font-semibold uppercase tracking-[0.06em] text-[hsl(var(--success))]">
                            Nueva
                          </span>
                        )}
                        {/* Dos líneas en móvil, una en la tabla. Un título del
                            TED ronda los 120 caracteres y empieza por el
                            preámbulo administrativo: cortarlo en una línea a
                            375 px deja fuera el objeto del contrato, que es lo
                            único por lo que se mira el Radar.
                            `line-clamp-1` y no `truncate` para la tabla: son la
                            misma utilidad en las dos anchuras, así que el orden
                            en cascada lo decide el prefijo `md:` y no la
                            ordenación interna de Tailwind entre dos familias
                            distintas que escriben `display`. */}
                        <span
                          className={cn(
                            "min-w-0 line-clamp-2 text-[13px] leading-[1.35] tracking-[-0.005em]",
                            "md:line-clamp-1 md:leading-[1.3]",
                            isActive ? "font-semibold text-foreground" : "font-medium",
                          )}
                        >
                          {tender.titulo}
                        </span>
                      </div>
                      {/* Flujo inline, no flex: `text-overflow` se ignora en un
                          contenedor flex y la línea se cortaría a medias. */}
                      <div className="mt-0.5 block truncate font-mono text-[10.5px] leading-[1.3] text-muted-foreground/80">
                        {[tender.id_externo, tender.cpv ? `CPV ${tender.cpv}` : null, tender.ccaa]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                    </div>
                  </div>

                  {/* Órgano y tecnología son las dos columnas que se subordinan
                      en móvil: siguen ahí, en una línea secundaria bajo el
                      título, en vez de competir con score, plazo e importe. */}
                  <div className="flex min-w-0 items-center justify-between gap-2 md:contents">
                    <span className="min-w-0 flex-1 truncate text-xs leading-[1.35] text-muted-foreground">
                      {tender.organo_contratacion ?? "—"}
                    </span>

                    {tech ? (
                      <span className="max-w-[46%] flex-none justify-self-start truncate rounded-[5px] border border-[hsl(var(--info)/0.26)] bg-[hsl(var(--info)/0.1)] px-1.5 py-1 text-[11px] font-medium text-[hsl(var(--info))] md:max-w-full">
                        {tech}
                      </span>
                    ) : (
                      <span className="flex-none text-[11px] text-muted-foreground/60">—</span>
                    )}
                  </div>

                  <div className="flex items-center justify-between gap-3 md:contents">
                    <span className="tf-tnum font-mono text-[13px] font-semibold md:text-right">
                      {shortEur(tender.importe)}
                    </span>

                    <div className="flex flex-none flex-col items-end gap-1.5">
                      <span
                        className="tf-tnum font-mono text-xs font-semibold leading-none"
                        style={{ color: urg.color }}
                      >
                        {days != null ? `${days} d` : "—"}
                      </span>
                      <span className="block h-0.5 w-14 overflow-hidden rounded-sm bg-muted-foreground/20">
                        <span
                          className="block h-full w-full origin-left transition-transform duration-[420ms] ease-out"
                          style={{ background: urg.color, transform: `scaleX(${urg.ratio})` }}
                        />
                      </span>
                    </div>
                  </div>

                  {/* Las acciones tienen columna propia y no se superponen a
                      Importe ni a Plazo: al cambiar de fila nada se mueve.
                      En móvil están siempre visibles: revelarlas al seleccionar
                      es un gesto de hover, y en táctil convertiría descartar en
                      dos toques (uno para que aparezca el botón, otro para
                      pulsarlo). Solo a partir de `md` vuelven a depender de la
                      fila activa. */}
                  <div
                    data-slot="radar-acciones"
                    // `md:opacity-0` esconde el bloque pero lo deja en el orden
                    // de tabulación: 23 filas inactivas × 3 botones eran 69
                    // paradas invisibles, sin foco visible (WCAG 2.4.7). `inert`
                    // los saca del foco y del árbol de accesibilidad, y solo
                    // donde están ocultos: en la ficha móvil son visibles y
                    // siguen siendo alcanzables.
                    inert={enTabla && !isActive}
                    className={cn(
                      "flex items-center justify-end gap-2 border-t border-border/40 pt-2.5",
                      "md:gap-1.5 md:border-t-0 md:pt-0",
                      isActive
                        ? "md:animate-in md:fade-in-0 md:slide-in-from-right-2 md:duration-[170ms]"
                        : "md:pointer-events-none md:opacity-0",
                    )}
                  >
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          aria-label={`Descartar ${tender.titulo}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            dismiss(tender);
                          }}
                          // 36×36 en móvil. Los 26 px de la consola cumplen el
                          // mínimo de WCAG 2.5.8 (24×24) pero se fallan con el
                          // pulgar, y aquí el error cuesta una señal descartada.
                          className="tf-pressable grid h-9 w-9 place-items-center rounded-md border border-border/80 bg-card text-muted-foreground transition-colors duration-140 ease-out hover:border-destructive/50 hover:text-destructive md:h-6.5 md:w-6.5"
                        >
                          <X className="h-4 w-4 md:h-3 md:w-3" aria-hidden="true" />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>Descartar · X</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          aria-label={isFollowed ? `Dejar de seguir ${tender.titulo}` : `Seguir ${tender.titulo}`}
                          aria-pressed={isFollowed}
                          onClick={(event) => {
                            event.stopPropagation();
                            toggleFollow(tender);
                          }}
                          className={cn(
                            "tf-pressable grid h-9 w-9 place-items-center rounded-md border transition-colors duration-140 ease-out md:h-6.5 md:w-6.5",
                            isFollowed
                              ? "border-primary/50 bg-primary/16 text-primary"
                              : "border-border/80 bg-card text-muted-foreground hover:text-foreground",
                          )}
                        >
                          <Star
                            className={cn("h-4 w-4 md:h-3 md:w-3", isFollowed && "fill-current")}
                            aria-hidden="true"
                          />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>Seguir · S</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            void openPursuit(tender);
                          }}
                          // En móvil ocupa el resto de la línea: es la acción
                          // que se busca, y el borde derecho es donde cae el
                          // pulgar. En la tabla vuelve a su ancho de contenido.
                          className="tf-pressable h-9 flex-1 whitespace-nowrap rounded-md border border-primary/35 bg-primary/14 px-2.5 text-[12px] font-semibold text-primary transition-colors duration-140 ease-out hover:bg-primary/24 md:h-6.5 md:flex-none md:text-[11px]"
                        >
                          Abrir
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>Abrir oportunidad · ⏎</TooltipContent>
                    </Tooltip>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div className="flex h-[34px] min-w-0 flex-none items-center gap-3.5 border-t border-border/70 bg-card/60 px-3 text-[11px] text-muted-foreground md:px-3.5">
          <span className="tf-tnum truncate">{statusLine}</span>
          <span className="hidden text-muted-foreground/60 lg:inline">
            · top 24 del mercado abierto por potencial comercial
          </span>
          <div className="flex-1" />
          {SHORTCUTS.map((shortcut) => (
            <span key={shortcut.key} className="hidden items-center gap-1.5 md:inline-flex">
              <span className="rounded border border-border/70 px-1 py-0.5 font-mono text-[9px] font-medium">
                {shortcut.key}
              </span>
              {shortcut.label}
            </span>
          ))}
        </div>
      </section>

      {/* Decisión escrita: el inspector no baja de `xl`. Son 432 px de segunda
          superficie sobre la fila seleccionada; a 375 px o tapa la lista o la
          parte en dos. Lo accionable sí baja entero —seguir, descartar y abrir
          viven en la ficha—, así que lo que se pierde en móvil es contexto de
          lectura (desglose de score, línea de tiempo, competencia esperada), no
          capacidad. Ese contexto tiene pantalla propia en `/detalle?lic=`, que
          hoy solo se enlaza desde aquí: pendiente de resolver el acceso a ella
          desde la ficha sin convertir toda la fila en un enlace. */}
      <aside className="hidden w-[432px] flex-none flex-col bg-card/40 xl:flex">
        {active ? (
          <RadarInspector
            key={active.id_externo}
            tender={active}
            followed={followedIds.has(active.id_externo)}
            onFollow={() => toggleFollow(active)}
            onDismiss={() => dismiss(active)}
            onOpenPursuit={() => void openPursuit(active)}
            opening={createPursuit.isPending}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center px-8 text-center">
            <p className="text-[13px] leading-[1.5] text-muted-foreground">
              Selecciona una señal para ver su desglose de score, sus fechas y quién suele ganar
              en ese órgano.
            </p>
          </div>
        )}
      </aside>
    </div>
  );
}
