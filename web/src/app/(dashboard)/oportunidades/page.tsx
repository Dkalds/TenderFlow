"use client";

import * as React from "react";
import Link from "next/link";
import {
  BriefcaseBusiness,
  CircleCheckBig,
  CircleX,
  Clock3,
  type LucideIcon,
  RadioTower,
  Search,
  Trophy,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PursuitCard } from "@/components/pursuits/pursuit-card";
import { formatEur } from "@/components/pursuits/pursuit-presenters";
import { PanelEmpty, PanelError } from "@/components/console/panel";
import { type PursuitStatus, usePursuitMetrics, usePursuits } from "@/hooks/use-pursuits";
import { SpaceShell } from "@/components/layout/space-shell";
import { cn } from "@/lib/utils";

/**
 * Oportunidades — tablero de ejecución.
 *
 * Los cuatro carriles ocupan el alto de la pantalla y hacen scroll cada uno por
 * su cuenta, en vez de crecer hacia abajo y obligar a bajar la página entera
 * para ver el final del último. Las métricas van en una tira pegada a la
 * cabecera: son el marcador del tablero, no cuatro tarjetas sueltas.
 *
 * Se conserva todo lo de la pantalla anterior: los cuatro carriles con sus
 * agrupaciones de estado, las cuatro métricas, el buscador por título,
 * referencia y responsable, y los dos estados vacíos (sin oportunidades en
 * absoluto, y sin oportunidades en un carril).
 */

const LANES: { title: string; statuses: PursuitStatus[]; description: string }[] = [
  {
    title: "Por decidir",
    statuses: ["identified", "qualifying", "go_no_go"],
    description: "Identificadas, cualificando o en GO/NO-GO",
  },
  { title: "En preparación", statuses: ["preparing"], description: "Trabajo activo de la oferta" },
  { title: "Presentadas", statuses: ["submitted"], description: "Pendientes de resultado" },
  {
    title: "Cerradas",
    statuses: ["won", "lost", "withdrawn"],
    description: "Ganadas, perdidas o retiradas",
  },
];

function Metric({
  icon: Icon,
  label,
  value,
  loading,
}: {
  icon: LucideIcon;
  label: string;
  value: string | number | undefined;
  loading: boolean;
}) {
  return (
    <div className="flex min-w-0 items-center gap-3 bg-card px-4 py-3">
      <span className="grid h-8 w-8 flex-none place-items-center rounded-lg bg-primary/10 text-primary">
        <Icon className="h-4 w-4" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <div className="mb-1.5 truncate font-mono text-[8.5px] font-semibold uppercase tracking-[0.11em] text-muted-foreground">
          {label}
        </div>
        {loading ? (
          <Skeleton className="h-5 w-16 rounded" />
        ) : (
          <div className="tf-tnum font-mono text-[19px] font-semibold leading-none">
            {value ?? "—"}
          </div>
        )}
      </div>
    </div>
  );
}

export default function OportunidadesPage() {
  const [query, setQuery] = React.useState("");
  const pursuits = usePursuits();
  const metrics = usePursuitMetrics();
  const items = (pursuits.data?.items ?? []).filter(
    (pursuit) =>
      !query.trim() ||
      `${pursuit.tender_title ?? ""} ${pursuit.licitacion_id} ${pursuit.responsible_name ?? ""}`
        .toLocaleLowerCase("es")
        .includes(query.trim().toLocaleLowerCase("es")),
  );

  // El buscador por título, referencia y responsable vive en la cabecera del
  // espacio: es el control que gobierna los cuatro carriles.
  const search = (
    <label className="relative block w-56 flex-none" htmlFor="pursuit-search">
      <Search
        className="pointer-events-none absolute left-2.5 top-1.5 h-3.5 w-3.5 text-muted-foreground"
        aria-hidden="true"
      />
      <span className="sr-only">Buscar oportunidad</span>
      <Input
        id="pursuit-search"
        className="h-7 pl-8 text-xs"
        placeholder="Buscar oportunidad"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
    </label>
  );

  const empty = !pursuits.isLoading && !pursuits.error && (pursuits.data?.items?.length ?? 0) === 0;

  return (
    <SpaceShell spaceKey="oportunidades" actions={search} bleed>
      <div className="flex h-full min-h-0 flex-col">
        <section
          aria-label="Resumen de oportunidades"
          className="grid flex-none grid-cols-2 gap-px border-b border-border/70 bg-border/60 lg:grid-cols-4"
        >
          <Metric
            icon={Clock3}
            label="Identificadas"
            value={metrics.data?.pursuits_identified}
            loading={metrics.isLoading}
          />
          <Metric
            icon={CircleCheckBig}
            label="Presentadas"
            value={metrics.data?.pursuits_submitted}
            loading={metrics.isLoading}
          />
          <Metric
            icon={Trophy}
            label="Ganadas"
            value={metrics.data?.pursuits_won}
            loading={metrics.isLoading}
          />
          <Metric
            icon={CircleX}
            label="Adjudicado"
            value={metrics.data ? formatEur(metrics.data.awarded_amount_eur) : undefined}
            loading={metrics.isLoading}
          />
        </section>

        {pursuits.error ? (
          <div className="grid flex-1 place-items-center p-10">
            <PanelError
              title="No se pudieron cargar las oportunidades"
              detail={(pursuits.error as Error).message}
              onRetry={() => void pursuits.refetch()}
            />
          </div>
        ) : empty ? (
          <div className="grid flex-1 place-items-center p-10">
            <div className="max-w-[480px] rounded-xl border border-dashed border-border/60 px-8 py-11 text-center">
              <span className="mx-auto mb-3.5 grid h-11 w-11 place-items-center rounded-[11px] bg-muted-foreground/10 text-muted-foreground">
                <BriefcaseBusiness className="h-5 w-5" aria-hidden="true" />
              </span>
              <h3 className="mb-1.5 font-display text-[15px] font-semibold leading-[1.3]">
                Todavía no hay oportunidades
              </h3>
              <p className="mb-4 text-[12.5px] leading-[1.6] text-muted-foreground text-pretty">
                Convierte una señal del Radar en una oportunidad de equipo para empezar a hacerle
                seguimiento.
              </p>
              <Link
                href="/radar"
                className="tf-pressable inline-flex h-8 items-center gap-1.5 rounded-lg border border-primary/50 bg-linear-to-b from-primary to-[hsl(20_84%_55%)] px-3.5 text-[12.5px] font-semibold text-primary-foreground"
              >
                <RadioTower className="h-3.5 w-3.5" aria-hidden="true" />
                Ir al Radar
              </Link>
            </div>
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-border/50 md:grid-cols-2 xl:grid-cols-4">
            {LANES.map((lane) => {
              const laneItems = items.filter((item) => lane.statuses.includes(item.status));
              return (
                <section
                  key={lane.title}
                  aria-label={lane.title}
                  className="flex min-w-0 flex-col bg-background"
                >
                  <div className="flex-none border-b border-border/40 px-3.5 pb-2.5 pt-3">
                    <div className="flex items-baseline gap-2">
                      <h2 className="text-[12.5px] font-semibold">{lane.title}</h2>
                      <div className="flex-1" />
                      <span
                        className={cn(
                          "tf-tnum rounded px-1.5 py-0.5 font-mono text-[10px] font-medium",
                          laneItems.length
                            ? "bg-primary/16 text-primary"
                            : "bg-muted-foreground/12 text-muted-foreground",
                        )}
                      >
                        {laneItems.length}
                      </span>
                    </div>
                    <p className="mt-1 text-[10.5px] leading-[1.4] text-muted-foreground">
                      {lane.description}
                    </p>
                  </div>
                  <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-3 py-2.5">
                    {pursuits.isLoading ? (
                      <>
                        <Skeleton className="h-28 rounded-xl" />
                        <Skeleton className="h-28 rounded-xl" />
                      </>
                    ) : laneItems.length ? (
                      laneItems.map((pursuit) => <PursuitCard key={pursuit.id} pursuit={pursuit} />)
                    ) : (
                      <PanelEmpty message="Sin oportunidades en esta fase." />
                    )}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </div>
    </SpaceShell>
  );
}
