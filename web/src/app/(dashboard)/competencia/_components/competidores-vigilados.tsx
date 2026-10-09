"use client";

/**
 * Tus empresas vigiladas y sus movimientos, en carriles.
 *
 * Un carril por empresa, la ventana de 30 días de izquierda a derecha y una
 * marca por movimiento fechado: entrada en una CCAA nueva, en una familia CPV
 * nueva, o una racha de adjudicaciones. Debajo, los mismos movimientos como
 * lista, con el enlace a su licitación: el carril dice cuándo, la lista dice
 * qué.
 *
 * Todo lo calcula el backend (`/competitive/watchlist/movimientos`) sobre
 * adjudicaciones reales; aquí solo se pinta. Cada nombre lleva a la ficha de la
 * empresa, que es donde se deja de vigilar.
 *
 * Sin empresas vigiladas no hay nada que vigilar y el panel lo dice.
 */

import Link from "next/link";

import { EnlaceIr, Panel, PanelEmpty, PanelTitle, SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatDate, formatNumber } from "@/lib/utils";

import { useMovimientosVigiladas } from "../_hooks/use-vigilados";
import { carrilesDeVigiladas, type Carril, type Senal } from "../_hooks/vigilados";

const TIPO_ETIQUETA: Record<Senal["tipo"], string> = {
  nueva_ccaa: "Territorio nuevo",
  nuevo_cpv: "Nicho nuevo",
  racha: "Racha",
};

/** La forma de cada tipo de movimiento, centrada en el origen. */
function Forma({ tipo }: { tipo: Senal["tipo"] }) {
  if (tipo === "nueva_ccaa") return <rect x="-3.5" y="-3.5" width="7" height="7" rx="1" transform="rotate(45)" />;
  if (tipo === "nuevo_cpv") return <rect x="-3.5" y="-3.5" width="7" height="7" rx="1" />;
  return <circle r="4" />;
}

/** La forma suelta, para la leyenda y para la lista. */
function Icono({ tipo }: { tipo: Senal["tipo"] }) {
  return (
    <svg aria-hidden="true" className="h-3 w-3 flex-none fill-foreground" viewBox="-6 -6 12 12">
      <Forma tipo={tipo} />
    </svg>
  );
}

/** Lo que ha ganado en la ventana, o que no ha ganado nada. */
function actividad({ adjudicaciones, importe }: Carril): string {
  if (adjudicaciones === 0) return "sin adjudicaciones";
  const unidad = adjudicaciones === 1 ? "adjudicación" : "adjudicaciones";
  return `${formatNumber(adjudicaciones)} ${unidad} · ${formatCurrency(importe)}`;
}

/** Lo que el carril dice a quien no lo ve. */
function resumen(carril: Carril): string {
  if (carril.marcas.length === 0) return `${carril.nombre}: sin movimientos fechados en la ventana`;
  const marcas = carril.marcas.map((m) => `${TIPO_ETIQUETA[m.tipo]} el ${formatDate(m.fecha)}`);
  return `${carril.nombre}: ${marcas.join("; ")}`;
}

export function CompetidoresVigilados() {
  const { data, isLoading, isError } = useMovimientosVigiladas();

  if (isError) return null;

  const carriles = carrilesDeVigiladas(data);
  const senales = data?.senales ?? [];
  const dias = data?.dias;

  return (
    <Panel className="flex flex-col">
      <PanelTitle
        title="Tus vigilados"
        hint={dias != null ? `últimos ${formatNumber(dias)} días, sobre adjudicaciones` : undefined}
        className="mb-2"
      />
      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : carriles.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="No vigilas ninguna empresa"
          hint="Pulsa «Vigilar empresa» en el perfil de un competidor, o la estrella en el maestro de Empresas, para ver aquí su actividad y sus movimientos."
        />
      ) : (
        <div className="space-y-4">
          <div>
            <p className="mb-2 flex flex-wrap gap-x-3.5 gap-y-1 text-tf-micro text-muted-foreground">
              {(Object.keys(TIPO_ETIQUETA) as Senal["tipo"][]).map((tipo) => (
                <span key={tipo} className="inline-flex items-center gap-1.5">
                  <Icono tipo={tipo} />
                  {TIPO_ETIQUETA[tipo]}
                </span>
              ))}
            </p>
            {/* El orden es el del backend: más adjudicaciones primero. */}
            <ul aria-label="Empresas vigiladas" className="space-y-2.5">
              {carriles.map((carril) => (
                <li key={carril.empresa_id}>
                  <div className="flex min-w-0 items-baseline justify-between gap-3">
                    <Link
                      href={`/competencia/empresa/${carril.empresa_id}`}
                      className="min-w-0 truncate text-tf-body font-medium transition-colors hover:text-primary"
                    >
                      {carril.nombre}
                    </Link>
                    <span className="tf-tnum shrink-0 text-tf-meta text-muted-foreground">{actividad(carril)}</span>
                  </div>
                  {/* Aire a los lados: una marca del primer o del último día
                      se dibuja entera, no cortada por el borde. */}
                  <div className="mt-1 px-1.5">
                    <svg role="img" aria-label={resumen(carril)} className="h-3.5 w-full overflow-visible">
                      <line x1="0" y1="7" x2="100%" y2="7" className="stroke-border" />
                      {carril.marcas.map((marca) => (
                        <svg
                          key={`${marca.tipo}-${marca.fecha}-${marca.titulo}`}
                          x={`${marca.x}%`}
                          y="7"
                          className="overflow-visible fill-foreground stroke-card"
                          strokeWidth="1.5"
                        >
                          <Forma tipo={marca.tipo} />
                        </svg>
                      ))}
                    </svg>
                  </div>
                </li>
              ))}
            </ul>
            {data && (
              <p aria-hidden="true" className="mt-1 flex justify-between px-1.5 text-tf-micro text-muted-foreground">
                <span>{formatDate(data.desde)}</span>
                <span>hoy</span>
              </p>
            )}
          </div>

          <div>
            <SectionTitle>Movimientos</SectionTitle>
            {senales.length === 0 ? (
              <p className="text-tf-meta text-muted-foreground">Sin movimientos destacables en este periodo.</p>
            ) : (
              <ul aria-label="Movimientos" className="divide-y divide-border/40">
                {senales.map((s, i) => (
                  <li
                    key={`${s.tipo}-${s.empresa_id}-${s.licitacion_id ?? i}`}
                    className="flex items-start gap-2.5 py-2 first:pt-0 last:pb-0"
                  >
                    <span className="mt-1 flex-none">
                      <Icono tipo={s.tipo} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-tf-body font-medium">{s.titulo}</span>
                        <Badge variant="outline" size="sm">
                          {TIPO_ETIQUETA[s.tipo]}
                        </Badge>
                      </div>
                      <p className="text-tf-meta text-muted-foreground">
                        {s.detalle}
                        {s.fecha ? ` · ${formatDate(s.fecha)}` : ""}
                        {s.importe != null ? ` · ${formatCurrency(s.importe)}` : ""}
                      </p>
                    </div>
                    {s.licitacion_id && (
                      <EnlaceIr
                        href={`/detalle?lic=${encodeURIComponent(s.licitacion_id)}`}
                        aria-label={`Ver la licitación ${s.licitacion_id}`}
                        className="shrink-0"
                      >
                        Ver
                      </EnlaceIr>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {data?.senales_truncadas && (
              <p className="mt-2 text-tf-meta text-muted-foreground">Parcial: solo las primeras señales.</p>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
