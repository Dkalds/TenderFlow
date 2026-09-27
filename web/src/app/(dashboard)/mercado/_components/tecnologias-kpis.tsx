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

import { Panel, ROTULO_DATO, StatCell, StatStrip } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { cn, EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";

import type { TecnologiasResponse } from "../_hooks/use-tecnologias-view";

export function TecnologiasKpis({
  data,
  isLoading,
}: {
  data: TecnologiasResponse | undefined;
  isLoading: boolean;
}) {
  return (
    <StatStrip columns={4}>
      <StatCell
        label="Tecnologías detectadas"
        value={formatNumber(data?.n_tecnologias ?? 0)}
        hint={`${formatNumber(data?.sin_clasificar ?? 0)} licitaciones sin clasificar`}
        loading={isLoading}
      />
      <StatCell
        label="Tecnología líder"
        value={data?.tecnologia_lider ?? EMPTY}
        hint={data?.lider_count ? `${formatNumber(data.lider_count)} licitaciones` : undefined}
        loading={isLoading}
      />
      <StatCell
        label="Importe medio por tecnología"
        value={valorOEmpty(data?.importe_medio_global, formatCurrency)}
        loading={isLoading}
      />
      <StatCell
        label="Tasa de adjudicación"
        value={valorOEmpty(data?.tasa_adjudicacion_media, formatPercent)}
        hint="Media por tecnología"
        loading={isLoading}
      />
    </StatStrip>
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
    <Panel
      className={cn(
        "flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between",
        low && "border-warning/50",
      )}
    >
      <div>
        <p className={ROTULO_DATO}>Licitaciones con tecnología identificada</p>
        <p className={cn("mt-1 text-tf-title font-semibold", low && "text-warning")}>
          {isLoading ? "…" : formatPercent(pctClasificado)}
        </p>
        <p className="mt-0.5 text-tf-meta text-muted-foreground">
          {formatNumber(sin)} sin clasificar de {formatNumber(total)} licitaciones
          {low && ". Por debajo del 70 %, las cifras de esta vista se quedan cortas."}
        </p>
      </div>
      <Button asChild size="sm" variant={low ? "default" : "outline"}>
        <Link href="/active-learning">Revisar sin clasificar</Link>
      </Button>
    </Panel>
  );
}
