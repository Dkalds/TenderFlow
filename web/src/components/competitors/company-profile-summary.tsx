"use client";

import { ArrowDownRight, ArrowUpRight, Building2, MapPinned, Shapes, Target } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import { CompanyYearTrend } from "./company-year-trend";
import {
  buildExecutiveSummary,
  cpvFamilyLabel,
  type CompanyBreakdown,
  type CompanyProfileData,
} from "./company-profile-types";

function MetricCell({
  label,
  value,
  detail,
  delta,
}: {
  label: string;
  value: string;
  detail: string;
  delta?: number | null;
}) {
  const DeltaIcon = delta != null && delta < 0 ? ArrowDownRight : ArrowUpRight;

  return (
    <div className="min-w-0 p-4 md:p-5">
      <dt className="text-muted-foreground text-[11px] font-semibold tracking-[0.14em] uppercase">{label}</dt>
      <dd className="mt-2 truncate text-2xl font-semibold tracking-tight tabular-nums" title={value}>
        {value}
      </dd>
      <p className="text-muted-foreground mt-1.5 min-h-5 text-xs leading-5">
        {delta == null ? (
          detail
        ) : (
          <span
            className={cn(
              "inline-flex items-center gap-1 font-medium",
              delta >= 0 ? "text-primary" : "text-amber-700 dark:text-amber-300",
            )}
          >
            <DeltaIcon className="h-3.5 w-3.5" aria-hidden="true" />
            {delta >= 0 ? "+" : ""}
            {formatPercent(delta)} vs. periodo anterior
          </span>
        )}
      </p>
    </div>
  );
}

function FootprintItem({ icon: Icon, value, label }: { icon: typeof Building2; value: string; label: string }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3.5 md:px-5">
      <span className="bg-primary/10 text-primary grid h-9 w-9 shrink-0 place-items-center rounded-md">
        <Icon className="h-4 w-4" aria-hidden="true" />
      </span>
      <div>
        <p className="font-semibold tabular-nums">{value}</p>
        <p className="text-muted-foreground text-xs">{label}</p>
      </div>
    </div>
  );
}

function BreakdownColumn({
  title,
  description,
  rows,
  empty,
  cpv = false,
}: {
  title: string;
  description: string;
  rows: CompanyBreakdown[];
  empty: string;
  cpv?: boolean;
}) {
  return (
    <section className="min-w-0 p-5" aria-label={title}>
      <h3 className="font-semibold">{title}</h3>
      <p className="text-muted-foreground mt-0.5 text-xs">{description}</p>
      {rows.length ? (
        <div className="mt-5 space-y-4">
          {rows.slice(0, 5).map((row, index) => {
            const label = cpv ? cpvFamilyLabel(row.codigo) : row.label;
            return (
              <div key={`${row.codigo ?? row.label}-${index}`} className="space-y-1.5">
                <div className="flex items-start justify-between gap-3 text-sm">
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
      ) : (
        <p className="text-muted-foreground py-10 text-center text-sm">{empty}</p>
      )}
    </section>
  );
}

function toneBorder(tone: string): string {
  if (tone === "positive") return "border-l-emerald-500";
  if (tone === "warning") return "border-l-amber-500";
  if (tone === "negative") return "border-l-destructive";
  return "border-l-border";
}

export function CompanyProfileSummary({ profile }: { profile: CompanyProfileData }) {
  const totals = profile.totales;
  const position = profile.posicion_mercado;
  const comparison = profile.comparacion;

  return (
    <div className="space-y-8">
      <section
        className="border-primary/55 bg-card rounded-lg border border-l-4 px-5 py-4"
        aria-labelledby="profile-reading-title"
      >
        <p id="profile-reading-title" className="text-xs font-semibold tracking-[0.14em] uppercase">
          Perfil operativo
        </p>
        <p className="text-muted-foreground mt-1.5 max-w-5xl text-sm leading-6">{buildExecutiveSummary(profile)}</p>
      </section>

      <section aria-labelledby="profile-kpis-title">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 id="profile-kpis-title" className="text-lg font-semibold">
              Operativa en cifras
            </h2>
            <p className="text-muted-foreground mt-0.5 text-sm">Tamaño, ritmo, posición y presión competitiva</p>
          </div>
          <p className="text-muted-foreground text-xs">Datos del periodo seleccionado</p>
        </div>

        <div className="bg-card overflow-hidden rounded-xl border">
          <dl className="grid sm:grid-cols-2 xl:grid-cols-3 [&>*]:border-r [&>*]:border-b sm:[&>*:nth-child(2n)]:border-r-0 xl:[&>*:nth-child(2n)]:border-r xl:[&>*:nth-child(3n)]:border-r-0 [&>*:nth-last-child(-n+1)]:border-b-0 sm:[&>*:nth-last-child(-n+2)]:border-b-0 xl:[&>*:nth-last-child(-n+3)]:border-b-0">
            <MetricCell
              label="Importe adjudicado"
              value={formatCurrency(totals.importe_total)}
              detail="Volumen acumulado"
              delta={comparison.variacion_importe_pct}
            />
            <MetricCell
              label="Adjudicaciones"
              value={formatNumber(totals.contratos)}
              detail="Expedientes ganados"
              delta={comparison.variacion_contratos_pct}
            />
            <MetricCell
              label="Cuota y posición"
              value={`${formatPercent(position.cuota_pct)}${position.rank ? ` · #${position.rank}` : ""}`}
              detail={position.rank ? `entre ${formatNumber(position.empresas)} empresas` : "Sin posición calculable"}
            />
            <MetricCell
              label="Contrato típico"
              value={formatCurrency(totals.importe_mediano)}
              detail="Mediana adjudicada; reduce el efecto de extremos"
            />
            <MetricCell
              label="Baja media"
              value={formatPercent(totals.baja_media_pct)}
              detail="Descuento sobre el presupuesto de licitación"
            />
            <MetricCell
              label="Presión competitiva"
              value={totals.ofertas_medias == null ? "-" : `${totals.ofertas_medias.toFixed(1)} ofertas`}
              detail={`Cobertura del dato: ${formatPercent(totals.cobertura_ofertas_pct, 0)}`}
            />
          </dl>

          <div className="bg-muted/20 grid border-t sm:grid-cols-2 xl:grid-cols-4 xl:divide-x">
            <FootprintItem icon={Building2} value={formatNumber(totals.organos)} label="clientes públicos" />
            <FootprintItem icon={MapPinned} value={formatNumber(totals.territorios)} label="territorios" />
            <FootprintItem icon={Shapes} value={formatNumber(totals.familias_cpv)} label="familias CPV" />
            <FootprintItem
              icon={Target}
              value={formatPercent(totals.pct_oferta_unica)}
              label="adjudicaciones con oferta única"
            />
          </div>
        </div>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Progreso anual</CardTitle>
          <CardDescription>Importe adjudicado y contratos ganados por ejercicio</CardDescription>
        </CardHeader>
        <CardContent>
          <CompanyYearTrend rows={profile.por_anio} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Dónde y para quién opera</CardTitle>
          <CardDescription>Especialización, compradores recurrentes y huella territorial</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <div className="grid divide-y xl:grid-cols-3 xl:divide-x xl:divide-y-0">
            <BreakdownColumn
              title="Especialización"
              description="Familias CPV por peso económico"
              rows={profile.por_cpv}
              empty="Sin CPV clasificado"
              cpv
            />
            <BreakdownColumn
              title="Clientes principales"
              description={`Top 3: ${formatPercent(profile.concentracion_clientes.top3_importe_pct, 0)} del importe`}
              rows={profile.organos_principales}
              empty="Sin órgano identificado"
            />
            <BreakdownColumn
              title="Huella territorial"
              description="Distribución por comunidad autónoma"
              rows={profile.por_ccaa}
              empty="Sin territorio identificado"
            />
          </div>
          <p className="text-muted-foreground border-t px-5 py-3 text-xs">
            Dependencia del primer cliente: {formatPercent(profile.concentracion_clientes.top1_importe_pct)} del
            importe. La cobertura del número de ofertas es del {formatPercent(totals.cobertura_ofertas_pct)}.
          </p>
        </CardContent>
      </Card>

      {profile.movimientos.length ? (
        <section aria-labelledby="movements-title">
          <div className="mb-3 flex items-center gap-2">
            <Target className="text-primary h-4 w-4" aria-hidden="true" />
            <div>
              <h2 id="movements-title" className="font-semibold">
                Cambios relevantes
              </h2>
              <p className="text-muted-foreground text-xs">Señales que ayudan a interpretar el progreso reciente</p>
            </div>
          </div>
          <div className="bg-card divide-y overflow-hidden rounded-lg border">
            {profile.movimientos.slice(0, 4).map((movement, index) => (
              <div
                key={`${movement.kind}-${index}`}
                className={cn("border-l-4 px-4 py-3.5", toneBorder(movement.tone))}
              >
                <p className="text-sm font-medium">{movement.title}</p>
                <p className="text-muted-foreground mt-0.5 text-sm leading-5">{movement.detail}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
