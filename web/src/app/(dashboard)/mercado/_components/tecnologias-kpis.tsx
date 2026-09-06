"use client";

/**
 * La tira de KPIs de Tecnologías y la tarjeta de cobertura del clasificador.
 *
 * La segunda no es decorado: `sin_clasificar` es la métrica que dice cuánto del
 * corpus queda fuera de todo lo que la vista pinta encima, y por eso lleva su
 * denominador al lado y un CTA a la cola de etiquetado. Por debajo del 70 %
 * clasificado se pone en ámbar.
 */

import Link from "next/link";

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { cn, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";
import { Cpu, Trophy, DollarSign, Percent, ListChecks } from "lucide-react";

import type { TecnologiasResponse } from "../_hooks/use-tecnologias-view";

export function TecnologiasKpis({
  data,
  isLoading,
}: {
  data: TecnologiasResponse | undefined;
  isLoading: boolean;
}) {
  return (
    <KpiStrip columns={4}>
      <KpiCard
        title="Tecnologías detectadas"
        value={isLoading ? undefined : formatNumber(data?.n_tecnologias ?? 0)}
        subtitle={`${formatNumber(data?.sin_clasificar ?? 0)} sin clasificar`}
        icon={Cpu}
        loading={isLoading}
      />
      <KpiCard
        title="Tecnología líder"
        value={isLoading ? undefined : (data?.tecnologia_lider ?? "-")}
        subtitle={
          data?.lider_count
            ? `${formatNumber(data.lider_count)} licitaciones`
            : undefined
        }
        icon={Trophy}
        loading={isLoading}
      />
      <KpiCard
        title="Importe medio / tech"
        value={isLoading ? undefined : valorOEmpty(data?.importe_medio_global, formatCurrency)}
        icon={DollarSign}
        loading={isLoading}
      />
      <KpiCard
        title="Tasa adjudicación"
        value={isLoading ? undefined : valorOEmpty(data?.tasa_adjudicacion_media, formatPercent)}
        subtitle="media por tecnología"
        icon={Percent}
        loading={isLoading}
      />
    </KpiStrip>
  );
}

export function TecnologiasCobertura({
  data,
  isLoading,
}: {
  data: TecnologiasResponse | undefined;
  isLoading: boolean;
}) {
  const total = data?.total ?? 0;
  const sin = data?.sin_clasificar ?? 0;
  const pctClasificado = total > 0 ? ((total - sin) / total) * 100 : 0;
  const low = total > 0 && pctClasificado < 70;

  return (
    <Card className={cn(low && "border-amber-400 bg-amber-50/40 dark:bg-amber-950/20")}>
      <CardContent className="flex flex-col gap-3 pt-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm text-muted-foreground">Cobertura del clasificador</p>
          <p className="text-2xl font-bold">
            {isLoading ? "…" : `${pctClasificado.toFixed(1)}% clasificado`}
          </p>
          <p className="text-sm text-muted-foreground">
            {formatNumber(sin)} sin clasificar de {formatNumber(total)} licitaciones
          </p>
        </div>
        <Button asChild variant={low ? "default" : "outline"}>
          <Link href="/active-learning">
            <ListChecks className="mr-2 h-4 w-4" />
            Revisar sin clasificar
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
