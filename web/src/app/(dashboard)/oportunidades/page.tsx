"use client";

import * as React from "react";
import Link from "next/link";
import { BriefcaseBusiness, CircleCheckBig, CircleX, type LucideIcon, RadioTower, Search, Trophy } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PursuitCard } from "@/components/pursuits/pursuit-card";
import { formatEur } from "@/components/pursuits/pursuit-presenters";
import { PanelEmpty, PanelError } from "@/components/console/panel";
import { usePursuitMetrics, usePursuits } from "@/hooks/use-pursuits";
import { SpaceShell } from "@/components/layout/space-shell";
import { cn } from "@/lib/utils";
import { LANES, agruparPorExpediente } from "./_lib/carriles";

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
 *
 * La tira y los carriles NO cuentan lo mismo, y por eso cada métrica lleva su
 * matiz debajo: `/pursuits/metrics` devuelve el embudo **acumulado** de la
 * organización (`pursuits_identified` es toda oportunidad creada alguna vez,
 * `pursuits_submitted` toda la que llegó a presentarse), mientras que el badge
 * de cada carril cuenta el **estado actual**. Sin ese matiz, "Identificadas 4"
 * encima de un carril "Por decidir 1" se lee como tres tarjetas perdidas.
 *
 * Desde la revisión `v110` la unidad de todo esto es la **oportunidad**, no el
 * expediente: un expediente dividido en lotes puede tener una oportunidad por
 * lote. Por eso los carriles agrupan por expediente —las tarjetas de un mismo
 * expediente van juntas y bajo su título, distinguidas por el lote— y la tira
 * declara su unidad de conteo, que además viaja en el propio contrato
 * (`unidad_de_conteo`). Sin las dos cosas, "Oportunidades 6" sobre tres
 * expedientes parece un error de la pantalla.
 */

function Metric({
  icon: Icon,
  label,
  value,
  hint,
  loading,
}: {
  icon: LucideIcon;
  label: string;
  value: string | number | undefined;
  hint: string;
  loading: boolean;
}) {
  return (
    <div className="bg-card flex min-w-0 items-center gap-3 px-4 py-3">
      <span className="bg-primary/10 text-primary grid h-8 w-8 flex-none place-items-center rounded-lg">
        <Icon className="h-4 w-4" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <div className="text-muted-foreground mb-1.5 truncate font-mono text-[8.5px] font-semibold tracking-[0.11em] uppercase">
          {label}
        </div>
        {loading ? (
          <Skeleton className="h-5 w-16 rounded" />
        ) : (
          <div className="tf-tnum font-mono text-[19px] leading-none font-semibold">{value ?? "—"}</div>
        )}
        <div className="text-muted-foreground/80 mt-1 truncate text-[10px] leading-[1.3]">{hint}</div>
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
        className="text-muted-foreground pointer-events-none absolute top-1.5 left-2.5 h-3.5 w-3.5"
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
          className="border-border/70 bg-border/60 grid flex-none grid-cols-2 gap-px border-b lg:grid-cols-4"
        >
          <Metric
            icon={BriefcaseBusiness}
            label="Oportunidades"
            hint="Total creadas: una por lote, no por expediente"
            value={metrics.data?.pursuits_identified}
            loading={metrics.isLoading}
          />
          <Metric
            icon={CircleCheckBig}
            label="Presentadas"
            hint="Las que llegaron a presentarse"
            value={metrics.data?.pursuits_submitted}
            loading={metrics.isLoading}
          />
          <Metric
            icon={Trophy}
            label="Ganadas"
            hint="Con resultado adjudicado"
            value={metrics.data?.pursuits_won}
            loading={metrics.isLoading}
          />
          <Metric
            icon={CircleX}
            label="Adjudicado"
            hint="Suma de las ganadas"
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
            <div className="border-border/60 max-w-[480px] rounded-xl border border-dashed px-8 py-11 text-center">
              <span className="bg-muted-foreground/10 text-muted-foreground mx-auto mb-3.5 grid h-11 w-11 place-items-center rounded-[11px]">
                <BriefcaseBusiness className="h-5 w-5" aria-hidden="true" />
              </span>
              <h3 className="font-display mb-1.5 text-[15px] leading-[1.3] font-semibold">
                Todavía no hay oportunidades
              </h3>
              <p className="text-muted-foreground mb-4 text-[12.5px] leading-[1.6] text-pretty">
                Convierte una señal del Radar en una oportunidad de equipo para empezar a hacerle seguimiento.
              </p>
              <Link
                href="/radar"
                className="tf-pressable border-primary/50 from-primary text-primary-foreground inline-flex h-8 items-center gap-1.5 rounded-lg border bg-linear-to-b to-[hsl(20_84%_55%)] px-3.5 text-[12.5px] font-semibold"
              >
                <RadioTower className="h-3.5 w-3.5" aria-hidden="true" />
                Ir al Radar
              </Link>
            </div>
          </div>
        ) : (
          <div className="bg-border/50 grid min-h-0 flex-1 grid-cols-1 gap-px md:grid-cols-2 xl:grid-cols-4">
            {LANES.map((lane) => {
              const laneItems = items.filter((item) => lane.statuses.includes(item.status));
              return (
                <section key={lane.title} aria-label={lane.title} className="bg-background flex min-w-0 flex-col">
                  <div className="border-border/40 flex-none border-b px-3.5 pt-3 pb-2.5">
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
                    <p className="text-muted-foreground mt-1 text-[10.5px] leading-[1.4]">{lane.description}</p>
                  </div>
                  <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-3 py-2.5">
                    {pursuits.isLoading ? (
                      <>
                        <Skeleton className="h-28 rounded-xl" />
                        <Skeleton className="h-28 rounded-xl" />
                      </>
                    ) : laneItems.length ? (
                      agruparPorExpediente(laneItems).map((grupo) =>
                        grupo.items.length === 1 ? (
                          <PursuitCard key={grupo.items[0].id} pursuit={grupo.items[0]} />
                        ) : (
                          <section
                            key={grupo.licitacionId}
                            aria-label={grupo.titulo}
                            className="border-border/50 bg-muted/20 rounded-xl border p-1.5"
                          >
                            <div className="px-1.5 pt-1 pb-1.5">
                              <p className="truncate text-[11.5px] leading-snug font-semibold">{grupo.titulo}</p>
                              <p className="text-muted-foreground mt-0.5 text-[10.5px]">
                                {grupo.items.length} oportunidades de este expediente
                              </p>
                            </div>
                            <div className="flex flex-col gap-2">
                              {grupo.items.map((pursuit) => (
                                <PursuitCard key={pursuit.id} pursuit={pursuit} enExpediente />
                              ))}
                            </div>
                          </section>
                        ),
                      )
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
