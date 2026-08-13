"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  Bell,
  Briefcase,
  CalendarClock,
  ExternalLink,
  ListChecks,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { useFilters } from "@/lib/filters";
import { useDensity } from "@/lib/density";
import { cn, EMPTY, formatCompactCurrency, formatDate, formatNumber, truncate } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/empty-state";
import { PanelError, SectionTitle, StatCell, StatStrip } from "@/components/console/panel";
import { useOrganizationStore } from "@/hooks/use-organization";
import { useDismissRadarTender, useRestoreRadarTender } from "@/hooks/use-radar";
import {
  type AgendaUrgencia,
  type PipelineAgendaItem,
  useCreatePursuit,
  usePipelineAgenda,
  useUpdatePursuit,
} from "@/hooks/use-pursuits";

/**
 * Agenda — la vista de entrada de Mi Pipeline.
 *
 * Una sola cronología con tres clases de compromiso, agrupada por las bandas
 * de urgencia que ya vienen del backend (`GET /pursuits/agenda`): el frontend
 * no fusiona, no ordena y no clasifica (ADR-014). Los gestos son los del
 * Radar: J/K recorren, S sigue/anticipa, X descarta, ⏎ abre.
 */

const GRID = "grid-cols-[72px_26px_1fr_110px_96px] gap-3 px-3.5";

const BANDAS: { key: AgendaUrgencia; label: string; tone: string }[] = [
  { key: "vencida", label: "Vencidas", tone: "text-destructive" },
  { key: "hoy", label: "Hoy", tone: "text-destructive" },
  { key: "semana", label: "Próximos 7 días", tone: "text-amber-600 dark:text-amber-400" },
  { key: "mes", label: "Próximos 30 días", tone: "text-muted-foreground" },
  { key: "despues", label: "Más adelante", tone: "text-muted-foreground" },
  { key: "sin_fecha", label: "Sin fecha", tone: "text-muted-foreground" },
];

const CHIP_POR_BANDA: Record<AgendaUrgencia, string> = {
  vencida: "bg-destructive/12 text-destructive",
  hoy: "bg-destructive/12 text-destructive",
  semana: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  mes: "bg-secondary text-foreground/80",
  despues: "bg-muted-foreground/10 text-muted-foreground",
  sin_fecha: "bg-muted-foreground/10 text-muted-foreground",
};

const STATUS_LABELS: Record<string, string> = {
  identified: "Identificada",
  qualifying: "Calificando",
  go_no_go: "Go/No-go",
  preparing: "En preparación",
  submitted: "Presentada",
  won: "Ganada",
  lost: "Perdida",
  withdrawn: "Retirada",
};

const KIND_META = {
  pursuit: { icon: Briefcase, label: "Pursuit" },
  senal: { icon: Bell, label: "Señal" },
  renovacion: { icon: CalendarClock, label: "Renovación" },
} as const;

const SHORTCUTS = [
  { key: "J K", label: "navegar" },
  { key: "S", label: "seguir" },
  { key: "X", label: "descartar" },
  { key: "⏎", label: "abrir" },
];

function plazoChip(item: PipelineAgendaItem): string {
  if (item.dias_restantes == null) return EMPTY;
  if (item.urgencia === "hoy") return "hoy";
  if (item.dias_restantes < 0) return `−${Math.abs(item.dias_restantes)} d`;
  return `${item.dias_restantes} d`;
}

function metaLinea(item: PipelineAgendaItem): string {
  const partes: string[] = [];
  if (item.kind === "pursuit" && item.status) {
    partes.push(STATUS_LABELS[item.status] ?? item.status);
    if (item.next_action) partes.push(truncate(item.next_action, 44));
  }
  if (item.kind === "senal" && item.rule_nombre) partes.push(`Regla «${item.rule_nombre}»`);
  if (item.kind === "renovacion") {
    partes.push(
      item.adjudicatario ? `Adjudicatario: ${truncate(item.adjudicatario, 36)}` : "Contrato que vence",
    );
  }
  if (item.organo) partes.push(truncate(item.organo, 48));
  return partes.join(" · ");
}

export default function AgendaView() {
  const router = useRouter();
  const filters = useFilters();
  const compact = useDensity((s) => s.compact);
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
      dismissTender.mutate(item.licitacion_id);
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

  const listRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    node?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  if (error) {
    return (
      <PanelError
        title="No se pudo cargar la agenda"
        detail={(error as Error).message}
        onRetry={() => void refetch()}
        height={320}
      />
    );
  }

  const kpis = data?.kpis;
  const rowPad = compact ? "py-1.5" : "py-2.5";

  return (
    <div className="space-y-4">
      {/* Franja de compromisos: calculada en backend sobre el scope pedido */}
      <StatStrip columns={4} className="lg:grid-cols-[repeat(var(--console-stat-columns),minmax(0,1fr))]">
        <StatCell
          label="Vence en ≤7 días"
          loading={isLoading}
          value={kpis ? formatNumber(kpis.vence_semana) : EMPTY}
          hint={
            kpis && kpis.vence_semana > 0
              ? `${formatCompactCurrency(kpis.vence_semana_importe_eur)} en juego (incluye vencidas)`
              : "Pursuits abiertos con plazo esta semana"
          }
        />
        <StatCell
          label="Go/No-go pendientes"
          loading={isLoading}
          value={kpis ? formatNumber(kpis.go_no_go_pendientes) : EMPTY}
          hint="Sin decisión tomada"
        />
        <StatCell
          label="Sin próxima acción"
          loading={isLoading}
          value={kpis ? formatNumber(kpis.sin_proxima_accion) : EMPTY}
          accent={kpis && kpis.sin_proxima_accion > 0 ? "hsl(var(--warning))" : undefined}
          hint="Pursuits sin siguiente paso definido"
        />
        <StatCell
          label="Señales nuevas"
          loading={isLoading}
          value={kpis ? formatNumber(kpis.senales_nuevas) : EMPTY}
          hint="Matches de tus reglas sin triar"
        />
      </StatStrip>

      {(data?.pursuits_truncados || data?.senales_truncadas) && (
        <p
          role="status"
          className="rounded-lg border border-amber-500/25 bg-amber-500/8 px-3 py-1.5 text-[11.5px] text-amber-700 dark:text-amber-300"
        >
          La agenda está recortada
          {data.pursuits_truncados ? " (pursuits por encima del tope interno)" : ""}
          {data.senales_truncadas ? " (hay más señales que las mostradas)" : ""} — los KPIs
          describen solo lo listado.
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <section className="min-w-0 overflow-hidden rounded-xl border border-border/60 bg-card/70">
          <div className="flex h-10 items-center gap-2 border-b border-border/60 px-3.5">
            <button
              type="button"
              aria-pressed={soloMios}
              onClick={() => {
                setSoloMios((value) => !value);
                setSelected(0);
              }}
              className={cn(
                "tf-pressable h-6.5 rounded-full border px-2.5 text-[11.5px] font-medium transition-colors duration-150 ease-out",
                soloMios
                  ? "border-primary/30 bg-primary/10 text-primary"
                  : "border-border/70 text-muted-foreground hover:text-foreground",
              )}
            >
              Solo míos
            </button>
            <span className="text-[11px] text-muted-foreground">
              {isLoading ? "Cargando agenda…" : `${formatNumber(items.length)} compromisos`}
            </span>
            <div className="flex-1" />
            <div className="hidden items-center gap-2.5 md:flex">
              {SHORTCUTS.map((shortcut) => (
                <span key={shortcut.key} className="flex items-center gap-1 text-[10px] text-muted-foreground/70">
                  <kbd className="rounded border border-border/70 bg-secondary px-1 font-mono text-[9px]">
                    {shortcut.key}
                  </kbd>
                  {shortcut.label}
                </span>
              ))}
            </div>
          </div>

          <div ref={listRef} className="max-h-[calc(100vh-320px)] min-h-[240px] overflow-y-auto">
            {isLoading ? (
              <div className="flex flex-col gap-2.5 p-3.5">
                {Array.from({ length: 8 }, (_, index) => (
                  <span key={index} className="tf-shimmer block h-10 rounded-lg" style={{ opacity: 1 - index * 0.08 }} />
                ))}
              </div>
            ) : items.length === 0 ? (
              <EmptyState
                icon={ListChecks}
                title="Tu agenda está vacía"
                hint="Sigue señales desde el Radar o crea reglas en Mi Watchlist para que lleguen compromisos."
                actionLabel="Abrir el Radar"
                onAction={() => router.push("/radar")}
              />
            ) : (
              BANDAS.map((banda) => {
                const filas = items
                  .map((item, index) => ({ item, index }))
                  .filter(({ item }) => item.urgencia === banda.key);
                if (!filas.length) return null;
                return (
                  <React.Fragment key={banda.key}>
                    <div
                      className={cn(
                        "sticky top-0 z-10 border-b border-border/50 bg-card px-3.5 py-1 font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em]",
                        banda.tone,
                      )}
                    >
                      {banda.label} · {filas.length}
                    </div>
                    {filas.map(({ item, index }) => {
                      const Meta = KIND_META[item.kind];
                      const on = index === activeIndex;
                      return (
                        <div
                          key={`${item.kind}:${item.licitacion_id}`}
                          data-active={on || undefined}
                          role="button"
                          tabIndex={0}
                          onClick={() => setSelected(index)}
                          onDoubleClick={() => abrir(item)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") abrir(item);
                          }}
                          className={cn(
                            "grid cursor-pointer items-center border-b border-border/40 transition-colors duration-120 ease-out",
                            GRID,
                            rowPad,
                            on ? "bg-primary/8" : "hover:bg-secondary/60",
                          )}
                        >
                          <span
                            className={cn(
                              "tf-tnum inline-flex h-5 items-center justify-center rounded-full px-1.5 font-mono text-[10.5px] font-semibold",
                              CHIP_POR_BANDA[item.urgencia],
                            )}
                          >
                            {plazoChip(item)}
                          </span>
                          <Meta.icon
                            className="h-3.5 w-3.5 text-muted-foreground"
                            aria-label={Meta.label}
                          />
                          <div className="min-w-0">
                            <p className="truncate text-[12.5px] font-medium leading-[1.35]">
                              {item.titulo ?? item.licitacion_id}
                            </p>
                            <p className="truncate text-[10.5px] text-muted-foreground">
                              {metaLinea(item)}
                            </p>
                          </div>
                          <span className="tf-tnum text-right font-mono text-[11.5px] text-foreground/85">
                            {item.importe_eur != null ? formatCompactCurrency(item.importe_eur) : EMPTY}
                          </span>
                          <span className="flex justify-end">
                            {item.kind === "pursuit" ? (
                              <button
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  abrir(item);
                                }}
                                className="tf-pressable h-6 rounded-md border border-border/70 px-2 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
                              >
                                Abrir
                              </button>
                            ) : (
                              <span className="flex items-center gap-1">
                                <button
                                  type="button"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void seguir(item);
                                  }}
                                  className="tf-pressable h-6 rounded-md border border-primary/30 bg-primary/8 px-2 text-[11px] font-medium text-primary"
                                >
                                  {item.kind === "renovacion" ? "Anticipar" : "Seguir"}
                                </button>
                                {item.kind === "senal" && (
                                  <button
                                    type="button"
                                    aria-label="Descartar señal"
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      descartar(item);
                                    }}
                                    className="tf-pressable grid h-6 w-6 place-items-center rounded-md border border-border/70 text-muted-foreground transition-colors hover:text-destructive"
                                  >
                                    <X className="h-3 w-3" aria-hidden="true" />
                                  </button>
                                )}
                              </span>
                            )}
                          </span>
                        </div>
                      );
                    })}
                  </React.Fragment>
                );
              })
            )}
          </div>
        </section>

        <AgendaInspector item={active} onSeguir={seguir} onDescartar={descartar} onAbrir={abrir} />
      </div>
    </div>
  );
}

/**
 * Inspector en el mismo plano: el detalle del compromiso seleccionado y, para
 * pursuits, el editor de próxima acción (el dato que hace medible el abandono).
 */
/**
 * Editor de próxima acción de un pursuit. Va como componente aparte y montado
 * con `key` por selección/versión: cambiar de fila remonta el editor con el
 * valor del servidor, sin efectos que sincronicen estado (react-hooks).
 */
function NextActionEditor({ item }: { item: PipelineAgendaItem }) {
  const updatePursuit = useUpdatePursuit(item.pursuit_id ?? "");
  const [accion, setAccion] = React.useState(item.next_action ?? "");
  const [vence, setVence] = React.useState(item.next_action_due ?? "");

  const dirty = accion !== (item.next_action ?? "") || vence !== (item.next_action_due ?? "");

  const guardar = () => {
    if (item.version == null) return;
    updatePursuit.mutate(
      {
        next_action: accion.trim() || null,
        next_action_due: vence || null,
        expected_version: item.version,
      },
      {
        onSuccess: () => toast.success("Próxima acción guardada"),
        onError: (err) =>
          toast.error(
            err instanceof Error ? err.message : "No se pudo guardar (¿editada por otra persona?)",
          ),
      },
    );
  };

  return (
    <div>
      <SectionTitle>Próxima acción</SectionTitle>
      <Input
        value={accion}
        onChange={(event) => setAccion(event.target.value)}
        placeholder="Ej. Preparar borrador de oferta"
        maxLength={300}
        className="mb-2 h-8 text-[12px]"
      />
      <Input
        type="date"
        value={vence}
        onChange={(event) => setVence(event.target.value)}
        aria-label="Fecha límite de la próxima acción"
        className="mb-2 h-8 text-[12px]"
      />
      <button
        type="button"
        disabled={!dirty || updatePursuit.isPending}
        onClick={guardar}
        className={cn(
          "tf-pressable h-7 w-full rounded-md border text-[11.5px] font-medium transition-colors",
          dirty
            ? "border-primary/30 bg-primary/10 text-primary"
            : "border-border/60 text-muted-foreground/60",
        )}
      >
        {updatePursuit.isPending ? "Guardando…" : "Guardar"}
      </button>
    </div>
  );
}

function AgendaInspector({
  item,
  onSeguir,
  onDescartar,
  onAbrir,
}: {
  item: PipelineAgendaItem | undefined;
  onSeguir: (item: PipelineAgendaItem) => Promise<void>;
  onDescartar: (item: PipelineAgendaItem) => void;
  onAbrir: (item: PipelineAgendaItem) => void;
}) {
  const esPursuit = item?.kind === "pursuit" && item.pursuit_id != null;

  return (
    <aside className="hidden min-w-0 self-start rounded-xl border border-border/60 bg-card/70 p-4 xl:sticky xl:top-0 xl:block">
      {!item ? (
        <p className="py-8 text-center text-[11.5px] text-muted-foreground">
          Selecciona un compromiso para ver su detalle.
        </p>
      ) : (
        <div className="space-y-4">
          <div>
            <div className="mb-1.5 flex items-center gap-1.5">
              <span
                className={cn(
                  "inline-flex h-5 items-center rounded-full px-2 font-mono text-[10px] font-semibold",
                  CHIP_POR_BANDA[item.urgencia],
                )}
              >
                {plazoChip(item)}
              </span>
              <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                {KIND_META[item.kind].label}
              </span>
            </div>
            <h3 className="text-[13px] font-semibold leading-[1.4]">
              {item.titulo ?? item.licitacion_id}
            </h3>
            {item.due_date && (
              <p className="mt-1 text-[11px] text-muted-foreground">
                Vence el {formatDate(item.due_date)}
              </p>
            )}
          </div>

          <dl className="space-y-1.5 text-[11.5px]">
            {item.organo && (
              <div className="flex justify-between gap-3">
                <dt className="flex-none text-muted-foreground">Órgano</dt>
                <dd className="truncate text-right">{truncate(item.organo, 40)}</dd>
              </div>
            )}
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Importe</dt>
              <dd className="tf-tnum font-mono">
                {item.importe_eur != null ? formatCompactCurrency(item.importe_eur) : EMPTY}
              </dd>
            </div>
            {item.ccaa && (
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">CCAA</dt>
                <dd>{item.ccaa}</dd>
              </div>
            )}
            {item.kind === "pursuit" && item.status && (
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Estado</dt>
                <dd>{STATUS_LABELS[item.status] ?? item.status}</dd>
              </div>
            )}
            {item.kind === "pursuit" && item.responsible_name && (
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Responsable</dt>
                <dd className="truncate">{item.responsible_name}</dd>
              </div>
            )}
            {item.kind === "senal" && item.rule_nombre && (
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Regla</dt>
                <dd className="truncate">{item.rule_nombre}</dd>
              </div>
            )}
            {item.kind === "renovacion" && item.adjudicatario && (
              <div className="flex justify-between gap-3">
                <dt className="flex-none text-muted-foreground">Adjudicatario</dt>
                <dd className="truncate text-right">{truncate(item.adjudicatario, 36)}</dd>
              </div>
            )}
            {item.kind === "renovacion" && item.riesgo_cambio != null && (
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Riesgo de cambio</dt>
                <dd className="tf-tnum font-mono">{Math.round(item.riesgo_cambio * 100)}%</dd>
              </div>
            )}
          </dl>

          {esPursuit && (
            <NextActionEditor
              key={`${item.licitacion_id}:${item.version ?? 0}`}
              item={item}
            />
          )}

          <div className="flex flex-wrap gap-1.5 border-t border-border/50 pt-3">
            {item.kind === "pursuit" ? (
              <button
                type="button"
                onClick={() => onAbrir(item)}
                className="tf-pressable h-7 flex-1 rounded-md border border-primary/30 bg-primary/10 px-2.5 text-[11.5px] font-medium text-primary"
              >
                Abrir ficha
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => void onSeguir(item)}
                  className="tf-pressable h-7 flex-1 rounded-md border border-primary/30 bg-primary/10 px-2.5 text-[11.5px] font-medium text-primary"
                >
                  {item.kind === "renovacion" ? "Anticipar pursuit" : "Seguir"}
                </button>
                {item.kind === "senal" && (
                  <button
                    type="button"
                    onClick={() => onDescartar(item)}
                    className="tf-pressable h-7 rounded-md border border-border/70 px-2.5 text-[11.5px] font-medium text-muted-foreground hover:text-destructive"
                  >
                    Descartar
                  </button>
                )}
              </>
            )}
            {item.url && (
              // Enlace a la página del expediente en PLACSP, nunca al documento:
              // los enlaces directos a pliegos llevan tokens rotativos y caducan.
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="tf-pressable inline-flex h-7 items-center gap-1 rounded-md border border-border/70 px-2.5 text-[11.5px] font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                PLACSP
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
