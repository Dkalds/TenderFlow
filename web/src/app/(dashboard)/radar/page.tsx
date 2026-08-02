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
import { useFilters } from "@/lib/filters";
import { useDensity } from "@/lib/density";
import { getJSON, setJSON } from "@/lib/storage";
import { cn, formatNumber } from "@/lib/utils";
import { type RadarTender, useRadar } from "@/hooks/use-radar";
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
 * Alcance real de la lista (`hooks/use-radar.ts`): son las 24 licitaciones más
 * recientes reordenadas por score, no el top-24 por score del corpus. El pie de
 * la consola lo dice, porque prometer priorización global sería mentir.
 */

const GRID = "grid-cols-[46px_1fr_176px_132px_108px_96px_108px] gap-3 px-3.5";
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

/** Marca de la última visita, para el punto «nueva» de cada fila. */
const LAST_VISIT_KEY = "radar-last-visit";

export default function RadarPage() {
  const router = useRouter();
  const filters = useFilters();
  const compact = useDensity((s) => s.compact);
  const tecnologia = filters.tecnologias[0] ?? null;
  const { data, isLoading, isRanking, error, refetch } = useRadar(tecnologia);

  const { data: watched = [] } = useWatchlistItems();
  const addWatchlist = useAddWatchlistItem();
  const removeWatchlist = useRemoveWatchlistItem();
  const createPursuit = useCreatePursuit();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);

  const [segment, setSegment] = React.useState<SegmentKey>("bandeja");
  const [sort, setSort] = React.useState<SortKey>("score");
  const [selected, setSelected] = React.useState(0);
  const [dismissed, setDismissed] = React.useState<Set<string>>(() => new Set());

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

  const counts = React.useMemo(
    () => ({
      bandeja: all.filter((t) => !dismissed.has(t.id_externo) && !followedIds.has(t.id_externo))
        .length,
      siguiendo: all.filter((t) => followedIds.has(t.id_externo)).length,
      descartadas: all.filter((t) => dismissed.has(t.id_externo)).length,
      todas: all.length,
    }),
    [all, dismissed, followedIds],
  );

  const rows = React.useMemo(() => {
    const filtered = all.filter((tender) => {
      if (segment === "bandeja")
        return !dismissed.has(tender.id_externo) && !followedIds.has(tender.id_externo);
      if (segment === "siguiendo") return followedIds.has(tender.id_externo);
      if (segment === "descartadas") return dismissed.has(tender.id_externo);
      return true;
    });
    return filtered.slice().sort((a, b) => {
      if (sort === "score") return (b.score ?? -1) - (a.score ?? -1);
      if (sort === "plazo") return (daysLeft(a.fecha_limite) ?? 9999) - (daysLeft(b.fecha_limite) ?? 9999);
      return (b.importe ?? 0) - (a.importe ?? 0);
    });
  }, [all, segment, sort, dismissed, followedIds]);

  const activeIndex = Math.min(selected, Math.max(0, rows.length - 1));
  const active: RadarTender | undefined = rows[activeIndex];

  const restore = React.useCallback((id: string) => {
    setDismissed((current) => {
      const next = new Set(current);
      next.delete(id);
      return next;
    });
  }, []);

  // El descarte vive sólo en memoria: no hay endpoint de dismiss en el backend
  // (P1 en `docs/IMPROVEMENT_BACKLOG.md`). Mientras sea así, la acción se
  // acompaña de un deshacer inmediato y el copy lo dice.
  const dismiss = React.useCallback(
    (tender: RadarTender) => {
      setDismissed((current) => new Set(current).add(tender.id_externo));
      toast("Señal descartada en esta sesión", {
        description: tender.titulo,
        action: { label: "Deshacer", onClick: () => restore(tender.id_externo) },
      });
    },
    [restore],
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
        const pursuit = await createPursuit.mutateAsync({ licitacion_id: tender.id_externo });
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
  // mientras el foco está en un campo de texto, para no secuestrar la escritura.
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
      : `${formatNumber(rows.length)} filas · ${counts.bandeja} por revisar · ${counts.siguiendo} en seguimiento${
          isRanking ? " · ordenando por afinidad…" : ""
        }`;

  return (
    <div className="flex h-[calc(100vh-52px)] min-h-0">
      <main className="flex min-w-0 flex-1 flex-col border-r border-border/70">
        {/* Segmentos y orden */}
        <div className="flex h-11 flex-none items-center gap-0.5 border-b border-border/60 px-3.5">
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
                  "tf-pressable inline-flex h-7 items-center gap-[7px] rounded-md border px-2.5 text-[12.5px] font-medium transition-colors duration-150 ease-out",
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
          <div className="flex-1" />
          {dismissed.size > 0 && (
            <button
              type="button"
              onClick={() => setDismissed(new Set())}
              className="tf-pressable mr-1.5 h-6 rounded-md border border-border/70 px-2 text-[11px] font-medium text-muted-foreground transition-colors duration-140 ease-out hover:text-foreground"
            >
              Restaurar {dismissed.size} descartada{dismissed.size === 1 ? "" : "s"}
            </button>
          )}
          <span className="mr-1.5 font-mono text-[8.5px] font-semibold uppercase tracking-[0.11em] text-muted-foreground/70">
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
                  "tf-pressable h-6 rounded-md border px-2 text-[11px] font-medium transition-colors duration-150 ease-out",
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

        {/* Cabecera de columnas */}
        <div
          className={cn(
            "grid h-[30px] flex-none items-center border-b border-border/70 bg-card/50 font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground",
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

        <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto">
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
                  onKeyDown={(event) => {
                    if (event.key === " ") {
                      event.preventDefault();
                      setSelected(index);
                    }
                  }}
                  style={{ height: rowHeight }}
                  className={cn(
                    "relative grid cursor-pointer items-center border-b border-border/40 transition-colors duration-110 ease-out",
                    GRID,
                    isActive ? "bg-primary/9" : "hover:bg-primary/5",
                  )}
                >
                  <span
                    aria-hidden="true"
                    className="absolute inset-y-0 left-0 w-0.5 transition-colors duration-110 ease-out"
                    style={{ background: isActive ? bandColor(tender.band) : "transparent" }}
                  />

                  <div className="flex flex-col items-start gap-0.5">
                    <span
                      className="tf-tnum font-mono text-[15px] font-semibold leading-none"
                      style={{ color: bandColor(tender.band) }}
                    >
                      {tender.score != null ? Math.round(tender.score) : "—"}
                    </span>
                    <span className="font-mono text-[8px] font-medium uppercase leading-none tracking-[0.04em] text-muted-foreground">
                      {tender.band ?? (isRanking ? "…" : "s/p")}
                    </span>
                  </div>

                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-[7px]">
                      {isNew && (
                        <span className="flex-none rounded border border-[hsl(var(--success)/0.3)] bg-[hsl(var(--success)/0.12)] px-1 py-0.5 font-mono text-[8px] font-semibold uppercase tracking-[0.06em] text-[hsl(var(--success))]">
                          Nueva
                        </span>
                      )}
                      <span
                        className={cn(
                          "truncate text-[13px] leading-[1.3] tracking-[-0.005em]",
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

                  <span className="truncate text-xs leading-[1.35] text-muted-foreground">
                    {tender.organo_contratacion ?? "—"}
                  </span>

                  {tech ? (
                    <span className="max-w-full justify-self-start truncate rounded-[5px] border border-[hsl(var(--info)/0.26)] bg-[hsl(var(--info)/0.1)] px-1.5 py-1 text-[11px] font-medium text-[hsl(var(--info))]">
                      {tech}
                    </span>
                  ) : (
                    <span className="text-[11px] text-muted-foreground/60">—</span>
                  )}

                  <span className="tf-tnum text-right font-mono text-[13px] font-semibold">
                    {shortEur(tender.importe)}
                  </span>

                  <div className="flex flex-col items-end gap-1.5">
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

                  {/* Las acciones tienen columna propia y no se superponen a
                      Importe ni a Plazo: al cambiar de fila nada se mueve. */}
                  <div
                    className={cn(
                      "flex items-center justify-end gap-1.5",
                      isActive
                        ? "animate-in fade-in-0 slide-in-from-right-2 duration-[170ms]"
                        : "pointer-events-none opacity-0",
                    )}
                  >
                    <button
                      type="button"
                      title="Descartar · X"
                      aria-label={`Descartar ${tender.titulo}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        dismiss(tender);
                      }}
                      className="tf-pressable grid h-6.5 w-6.5 place-items-center rounded-md border border-border/80 bg-card text-muted-foreground transition-colors duration-140 ease-out hover:border-destructive/50 hover:text-destructive"
                    >
                      <X className="h-3 w-3" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      title="Seguir · S"
                      aria-label={isFollowed ? `Dejar de seguir ${tender.titulo}` : `Seguir ${tender.titulo}`}
                      aria-pressed={isFollowed}
                      onClick={(event) => {
                        event.stopPropagation();
                        toggleFollow(tender);
                      }}
                      className={cn(
                        "tf-pressable grid h-6.5 w-6.5 place-items-center rounded-md border transition-colors duration-140 ease-out",
                        isFollowed
                          ? "border-primary/50 bg-primary/16 text-primary"
                          : "border-border/80 bg-card text-muted-foreground hover:text-foreground",
                      )}
                    >
                      <Star className={cn("h-3 w-3", isFollowed && "fill-current")} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      title="Abrir oportunidad · ⏎"
                      onClick={(event) => {
                        event.stopPropagation();
                        void openPursuit(tender);
                      }}
                      className="tf-pressable h-6.5 whitespace-nowrap rounded-md border border-primary/35 bg-primary/14 px-2.5 text-[11px] font-semibold text-primary transition-colors duration-140 ease-out hover:bg-primary/24"
                    >
                      Abrir
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div className="flex h-[34px] flex-none items-center gap-3.5 border-t border-border/70 bg-card/60 px-3.5 text-[11px] text-muted-foreground">
          <span className="tf-tnum">{statusLine}</span>
          <span className="hidden text-muted-foreground/60 lg:inline">
            · las 24 más recientes, reordenadas por afinidad
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
      </main>

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
