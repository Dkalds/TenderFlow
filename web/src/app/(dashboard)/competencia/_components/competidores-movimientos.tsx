"use client";

/**
 * «Movimientos» de las empresas vigiladas (RFC ux-competidores #4).
 *
 * Señales proactivas sobre la watchlist de empresas, sin tener que abrir el
 * dossier de cada una: entrada en una CCAA o una familia CPV nueva y rachas de
 * adjudicaciones en los últimos 30 días. Todo lo calcula el backend
 * (`/competitive/watchlist/movimientos`) sobre adjudicaciones reales; aquí sólo
 * se pinta. No depende del ámbito global a propósito: la watchlist es el
 * ámbito, y una señal «entra en Galicia» no puede desaparecer porque la barra
 * filtre por Madrid.
 *
 * Sin empresas vigiladas no hay nada que vigilar y la tarjeta lo dice.
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Flame, MapPin, Shapes } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { formatCurrency, formatNumber } from "@/lib/utils";

type Movimientos = Schemas["MovimientosVigiladasResult"];
type Senal = Schemas["SenalCompetitiva"];

const DIAS = 30;

const ICONOS: Record<Senal["tipo"], typeof Flame> = {
  nueva_ccaa: MapPin,
  nuevo_cpv: Shapes,
  racha: Flame,
};

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
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Movimientos de tus competidores vigilados</CardTitle>
        <CardDescription>
          Últimos {DIAS} días, sobre adjudicaciones: entradas en territorios o nichos nuevos y rachas.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : empresas.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No vigilas ninguna empresa. Abre el dossier de un competidor y pulsa «Vigilar» para
            recibir aquí sus movimientos.
          </p>
        ) : senales.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            Sin movimientos destacables de tus {formatNumber(empresas.length)} empresas vigiladas en
            este periodo ({formatNumber(empresas.reduce((s, e) => s + e.adjudicaciones, 0))}{" "}
            adjudicaciones en total).
          </p>
        ) : (
          <ul className="space-y-2">
            {senales.map((s, i) => {
              const Icono = ICONOS[s.tipo];
              return (
                <li
                  key={`${s.tipo}-${s.empresa_id}-${s.licitacion_id ?? i}`}
                  className="flex items-start gap-3 rounded-md border p-3"
                >
                  <Icono className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{s.titulo}</span>
                      <Badge variant="outline">{TIPO_ETIQUETA[s.tipo]}</Badge>
                    </div>
                    <p className="text-muted-foreground text-xs">
                      {s.detalle}
                      {s.fecha ? ` · ${s.fecha}` : ""}
                      {s.importe != null ? ` · ${formatCurrency(s.importe)}` : ""}
                    </p>
                  </div>
                  {s.licitacion_id && (
                    <Link
                      href={`/detalle?lic=${encodeURIComponent(s.licitacion_id)}`}
                      className="text-primary shrink-0 text-xs underline-offset-4 hover:underline"
                      aria-label={`Ver la licitación ${s.licitacion_id}`}
                    >
                      Ver
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {data?.senales_truncadas && (
          <p className="text-muted-foreground mt-2 text-xs">Se muestran las primeras señales.</p>
        )}
      </CardContent>
    </Card>
  );
}
