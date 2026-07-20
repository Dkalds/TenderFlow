"use client";

import { Sparkles, Target, TrendingDown, TrendingUp } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import {
  buildExecutiveSummary,
  cpvFamilyLabel,
  type CompanyBreakdown,
  type CompanyProfileData,
} from "./company-profile-types";

function Delta({ value }: { value: number | null }) {
  if (value == null) {
    return <span className="text-muted-foreground text-xs">Sin base comparable</span>;
  }
  const Icon = value >= 0 ? TrendingUp : TrendingDown;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium",
        value >= 0 ? "text-emerald-700 dark:text-emerald-300" : "text-amber-700 dark:text-amber-300",
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {value >= 0 ? "+" : ""}
      {formatPercent(value)} frente al periodo anterior
    </span>
  );
}

function MetricCard({
  eyebrow,
  value,
  detail,
  delta,
}: {
  eyebrow: string;
  value: string;
  detail?: string;
  delta?: number | null;
}) {
  return (
    <Card className="hover:border-border min-w-0">
      <CardContent className="p-4">
        <p className="text-muted-foreground text-[11px] font-semibold tracking-[0.16em] uppercase">{eyebrow}</p>
        <p className="mt-2 truncate text-2xl font-semibold tracking-tight tabular-nums" title={value}>
          {value}
        </p>
        <div className="mt-2 min-h-5">
          {delta !== undefined ? <Delta value={delta} /> : <p className="text-muted-foreground text-xs">{detail}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function BreakdownList({ rows, empty, cpv = false }: { rows: CompanyBreakdown[]; empty: string; cpv?: boolean }) {
  if (!rows.length) {
    return <p className="text-muted-foreground py-8 text-center text-sm">{empty}</p>;
  }
  return (
    <div className="space-y-4">
      {rows.slice(0, 7).map((row, index) => {
        const label = cpv ? cpvFamilyLabel(row.codigo) : row.label;
        return (
          <div key={`${row.codigo ?? row.label}-${index}`} className="space-y-1.5">
            <div className="flex items-start justify-between gap-4 text-sm">
              <div className="min-w-0">
                <p className="truncate font-medium" title={label}>
                  {label}
                </p>
                <p className="text-muted-foreground text-xs">{formatNumber(row.contratos)} adjudicaciones</p>
              </div>
              <div className="shrink-0 text-right">
                <p className="font-medium tabular-nums">{formatCurrency(row.importe)}</p>
                <p className="text-muted-foreground text-xs">{formatPercent(row.cuota_empresa_pct, 0)}</p>
              </div>
            </div>
            <div className="bg-muted h-1.5 overflow-hidden rounded-full">
              <div
                className="bg-primary/75 h-full rounded-full"
                style={{ width: `${Math.max(2, row.cuota_empresa_pct)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function toneClasses(tone: string): string {
  if (tone === "positive") return "border-emerald-500/25 bg-emerald-500/5";
  if (tone === "warning") return "border-amber-500/25 bg-amber-500/5";
  if (tone === "negative") return "border-destructive/25 bg-destructive/5";
  return "border-border bg-muted/25";
}

export function CompanyProfileSummary({ profile }: { profile: CompanyProfileData }) {
  const totals = profile.totales;
  const position = profile.posicion_mercado;
  const comparison = profile.comparacion;

  return (
    <div className="space-y-6">
      <Card className="border-primary/20 bg-primary/[0.035] hover:border-primary/20">
        <CardContent className="flex gap-3 p-5">
          <Sparkles className="text-primary mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
          <div>
            <p className="text-primary text-xs font-semibold tracking-[0.15em] uppercase">Lectura ejecutiva</p>
            <p className="mt-1.5 max-w-5xl text-sm leading-6">{buildExecutiveSummary(profile)}</p>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          eyebrow="Volumen adjudicado"
          value={formatCurrency(totals.importe_total)}
          delta={comparison.variacion_importe_pct}
        />
        <MetricCard
          eyebrow="Adjudicaciones"
          value={formatNumber(totals.contratos)}
          delta={comparison.variacion_contratos_pct}
        />
        <MetricCard
          eyebrow="Cuota en el segmento"
          value={formatPercent(position.cuota_pct)}
          detail={
            position.rank
              ? `Posición #${position.rank} de ${formatNumber(position.empresas)}`
              : "Sin posición calculable"
          }
        />
        <MetricCard
          eyebrow="Ticket mediano"
          value={formatCurrency(totals.importe_mediano)}
          detail="Más robusto que el promedio ante contratos extremos"
        />
      </div>

      <div className="bg-card grid grid-cols-3 gap-3 rounded-lg border p-4">
        {[
          [totals.organos, "clientes públicos"],
          [totals.territorios, "territorios"],
          [totals.familias_cpv, "familias CPV"],
        ].map(([value, label]) => (
          <div key={label}>
            <p className="text-xl font-semibold tabular-nums">{formatNumber(Number(value))}</p>
            <p className="text-muted-foreground text-xs">{label}</p>
          </div>
        ))}
      </div>

      {profile.movimientos.length ? (
        <section aria-labelledby="movements-title">
          <div className="mb-3 flex items-center gap-2">
            <Target className="text-primary h-4 w-4" aria-hidden="true" />
            <h2 id="movements-title" className="font-semibold">
              Movimientos y señales
            </h2>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {profile.movimientos.map((movement, index) => (
              <div
                key={`${movement.kind}-${index}`}
                className={cn("rounded-lg border p-4", toneClasses(movement.tone))}
              >
                <p className="font-medium">{movement.title}</p>
                <p className="text-muted-foreground mt-1 text-sm leading-5">{movement.detail}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Especialización</CardTitle>
            <CardDescription>Familias CPV por peso económico</CardDescription>
          </CardHeader>
          <CardContent>
            <BreakdownList rows={profile.por_cpv} empty="Sin CPV clasificado" cpv />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Clientes principales</CardTitle>
            <CardDescription>
              Top 3: {formatPercent(profile.concentracion_clientes.top3_importe_pct, 0)} del importe
            </CardDescription>
          </CardHeader>
          <CardContent>
            <BreakdownList rows={profile.organos_principales} empty="Sin órgano identificado" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Huella territorial</CardTitle>
            <CardDescription>Distribución por comunidad autónoma</CardDescription>
          </CardHeader>
          <CardContent>
            <BreakdownList rows={profile.por_ccaa} empty="Sin territorio identificado" />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Comportamiento competitivo</CardTitle>
          <CardDescription>Los indicadores de ofertas usan solo adjudicaciones con ese dato disponible</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            <div>
              <p className="text-muted-foreground text-xs font-medium">Baja media</p>
              <p className="mt-1 text-xl font-semibold tabular-nums">{formatPercent(totals.baja_media_pct)}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs font-medium">Ofertas recibidas</p>
              <p className="mt-1 text-xl font-semibold tabular-nums">
                {totals.ofertas_medias == null ? "-" : totals.ofertas_medias.toFixed(1)}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs font-medium">Con oferta única</p>
              <p className="mt-1 text-xl font-semibold tabular-nums">{formatPercent(totals.pct_oferta_unica)}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs font-medium">Dependencia del primer cliente</p>
              <p className="mt-1 text-xl font-semibold tabular-nums">
                {formatPercent(profile.concentracion_clientes.top1_importe_pct)}
              </p>
            </div>
          </div>
          <p className="text-muted-foreground mt-5 border-t pt-4 text-xs">
            Cobertura del dato de ofertas: {formatPercent(totals.cobertura_ofertas_pct)}. Un porcentaje bajo reduce la
            comparabilidad de la presión competitiva.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
