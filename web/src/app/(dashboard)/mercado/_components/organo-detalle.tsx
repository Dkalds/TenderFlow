"use client";

/**
 * Panel del órgano abierto.
 *
 * Era un Sheet modal que tapaba el ranking del que venías, justo cuando lo que
 * quieres es comparar dos órganos. Ahora vive en el mismo plano y el ranking
 * sigue ahí para saltar al siguiente.
 */

import dynamic from "next/dynamic";
import { startTransition } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { KpiCard } from "@/components/charts/kpi-card";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { X, Hash, Trophy, Clock, Users, TrendingUp } from "lucide-react";

import type { OrganoDetailResponse } from "../_hooks/use-organos-view";
import { OrganoTopScored } from "./organo-top-scored";

const OrganosAdjudicatariosChart = dynamic(() => import("@/components/charts/organos-charts").then(m => ({ default: m.OrganosAdjudicatariosChart })), { ssr: false, loading: () => <Skeleton className="h-[280px] w-full rounded-md" /> });
const OrganosEstacionalidadChart = dynamic(() => import("@/components/charts/organos-charts").then(m => ({ default: m.OrganosEstacionalidadChart })), { ssr: false, loading: () => <Skeleton className="h-[200px] w-full rounded-md" /> });

export function OrganoDetalle({
  organo,
  detalle,
  isLoading,
  onClose,
}: {
  organo: string;
  detalle: OrganoDetailResponse | undefined;
  isLoading: boolean;
  onClose: () => void;
}) {
  return (
    <aside
      aria-label={`Detalle de ${organo}`}
      className="hidden w-[420px] flex-none flex-col overflow-hidden rounded-xl border border-border/60 bg-card/40 xl:flex"
    >
      <div className="flex flex-none items-start gap-2 border-b border-border/60 px-3.5 py-2.5">
        <h2 className="min-w-0 flex-1 text-[13px] font-semibold leading-tight">{organo}</h2>
        <button
          type="button"
          aria-label="Cerrar detalle del órgano"
          onClick={() => startTransition(onClose)}
          className="tf-pressable grid h-6 w-6 flex-none place-items-center rounded-md border border-border/70 text-muted-foreground transition-colors hover:text-foreground"
        >
          <X className="h-3 w-3" aria-hidden="true" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3.5 pb-4">
        {isLoading ? (
          <div className="mt-6 space-y-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : detalle ? (
          <div className="mt-6 space-y-6">
            <div className="grid grid-cols-2 gap-3">
              <KpiCard
                title="Licitaciones"
                value={formatNumber(detalle.kpis.total_licitaciones)}
                icon={Hash}
              />
              <KpiCard
                title="Importe Total"
                value={formatCurrency(detalle.kpis.importe_total)}
                subtitle={
                  detalle.kpis.importe_medio > 0
                    ? `medio ${formatCurrency(detalle.kpis.importe_medio)}`
                    : undefined
                }
                icon={TrendingUp}
              />
              <KpiCard
                title="% Adjudicado"
                value={formatPercent(detalle.kpis.pct_adjudicado)}
                subtitle="del total del órgano"
                icon={Trophy}
              />
              <KpiCard
                title="Lead Time Mediano"
                value={
                  detalle.kpis.lead_time_medio != null
                    ? `${Math.round(detalle.kpis.lead_time_medio)} días`
                    : "— d"
                }
                subtitle="pub → adj"
                icon={Clock}
              />
            </div>

            {detalle.kpis.top_adjudicatario && (
              <p className="text-xs text-muted-foreground">
                🏆 <strong>Top adjudicatario:</strong> {detalle.kpis.top_adjudicatario}
                {detalle.kpis.top_adj_importe > 0 && (
                  <> ({formatCurrency(detalle.kpis.top_adj_importe)})</>
                )}
              </p>
            )}

            {detalle.top_adjudicatarios?.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-sm">
                    <Users className="h-4 w-4" />
                    Top 10 Adjudicatarios
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <OrganosAdjudicatariosChart data={detalle.top_adjudicatarios} />
                </CardContent>
              </Card>
            )}

            {detalle.estacionalidad?.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Estacionalidad mensual</CardTitle>
                </CardHeader>
                <CardContent>
                  <OrganosEstacionalidadChart data={detalle.estacionalidad} />
                </CardContent>
              </Card>
            )}

            {detalle.top_scored?.length > 0 && <OrganoTopScored items={detalle.top_scored} />}
          </div>
        ) : (
          <p className="mt-6 text-sm text-muted-foreground">Sin datos del órgano.</p>
        )}
      </div>
    </aside>
  );
}
