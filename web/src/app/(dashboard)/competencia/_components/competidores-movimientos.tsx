"use client";

/**
 * Las empresas vigiladas y sus «movimientos» (RFC ux-competidores #4).
 *
 * La lista de vigiladas se pinta aquí desde 2026-09-25. Antes ninguna pantalla
 * la enseñaba: esta tarjeta sólo contaba cuántas había, igual que la línea de
 * contexto de Empresas, y para saber qué se vigilaba había que abrir fichas una
 * a una. Cada nombre lleva a su ficha, que es donde se deja de vigilar.
 *
 * Debajo van las señales proactivas sobre esas empresas, sin tener que abrir
 * el dossier de cada una: entrada en una CCAA o una familia CPV nueva y rachas
 * de adjudicaciones en los últimos 30 días. Todo lo calcula el backend
 * (`/competitive/watchlist/movimientos`) sobre adjudicaciones reales; aquí sólo
 * se pinta. No depende del ámbito global a propósito: la watchlist es el
 * ámbito, y una señal «entra en Galicia» no puede desaparecer porque la barra
 * filtre por Madrid.
 *
 * Sin empresas vigiladas no hay nada que vigilar y la tarjeta lo dice.
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { EnlaceIr, Panel, PanelEmpty, PanelTitle, SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { formatCurrency, formatDate, formatNumber } from "@/lib/utils";

type Movimientos = Schemas["MovimientosVigiladasResult"];
type Senal = Schemas["SenalCompetitiva"];
type Vigilada = Schemas["EmpresaVigiladaActividad"];

const DIAS = 30;

const TIPO_ETIQUETA: Record<Senal["tipo"], string> = {
  nueva_ccaa: "Territorio nuevo",
  nuevo_cpv: "Nicho nuevo",
  racha: "Racha",
};

export function CompetidoresMovimientos() {
  const { data, isLoading, isError } = useQuery<Movimientos>({
    queryKey: ["competitive", "watchlist-movimientos", DIAS],
    queryFn: () =>
      apiGet("/api/v1/competitive/watchlist/movimientos", {
        params: { query: { dias: DIAS } },
      }) as Promise<Movimientos>,
    staleTime: 5 * 60 * 1000,
  });

  if (isError) return null;

  const empresas = data?.empresas ?? [];
  const senales = data?.senales ?? [];

  return (
    <Panel>
      <PanelTitle title="Competidores vigilados" className="mb-1" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Últimos {DIAS} días, sobre adjudicaciones: lo que ha ganado cada una, entradas en territorios o nichos nuevos
        y rachas.
      </p>
      <div>
        {isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : empresas.length === 0 ? (
          <PanelEmpty
            size="sm"
            title="No vigilas ninguna empresa"
            hint="Pulsa «Vigilar empresa» en la ficha de un competidor, o la estrella en el maestro de Empresas, para ver aquí su actividad y sus movimientos."
          />
        ) : (
          <div className="space-y-5">
            {/* El orden es el del backend: más adjudicaciones primero. */}
            <ul aria-label="Empresas vigiladas" className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
              {empresas.map((empresa) => (
                <li key={empresa.empresa_id} className="flex min-w-0 items-baseline justify-between gap-3 text-tf-body">
                  <Link
                    href={`/competencia/empresa/${empresa.empresa_id}`}
                    className="min-w-0 truncate font-medium transition-colors hover:text-primary"
                  >
                    {empresa.nombre}
                  </Link>
                  <span className="shrink-0 text-tf-meta text-muted-foreground">{actividad(empresa)}</span>
                </li>
              ))}
            </ul>

            <div>
              <SectionTitle>Movimientos</SectionTitle>
              {senales.length === 0 ? (
                <p className="text-tf-meta text-muted-foreground">Sin movimientos destacables en este periodo.</p>
              ) : (
                <ul aria-label="Movimientos" className="space-y-2">
                  {senales.map((s, i) => (
                    <li
                      key={`${s.tipo}-${s.empresa_id}-${s.licitacion_id ?? i}`}
                      className="flex items-start gap-3 rounded-md border border-border/60 p-3"
                    >
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
      </div>
    </Panel>
  );
}

/** Lo que ha ganado en la ventana, o que no ha ganado nada. */
function actividad({ adjudicaciones, importe }: Vigilada): string {
  if (adjudicaciones === 0) return "sin adjudicaciones";
  const unidad = adjudicaciones === 1 ? "adjudicación" : "adjudicaciones";
  return `${formatNumber(adjudicaciones)} ${unidad} · ${formatCurrency(importe)}`;
}
