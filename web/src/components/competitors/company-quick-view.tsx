"use client";

import Link from "next/link";
import { ArrowDownRight, ArrowUpRight, CalendarDays, Eye, ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatCurrency, formatDate, formatNumber, formatPercent, truncate } from "@/lib/utils";

import { CompanyYearTrend } from "./company-year-trend";
import { buildExecutiveSummary, type CompanyAwardsData, type CompanyProfileData } from "./company-profile-types";

export interface CompanyQuickViewIdentity {
  nombre: string;
  nif?: string;
  count: number;
  importe: number;
  cuota: number;
  importe_medio?: number;
  baja_media?: number;
  ofertas_medias?: number;
}

interface CompanyQuickViewProps {
  empresaId: number;
  /** IDs adicionales del grupo cuando el competidor agrega varias identidades del maestro. */
  groupIds?: number[];
  company: CompanyQuickViewIdentity;
  profile?: CompanyProfileData;
  recentAwards?: CompanyAwardsData;
  isLoadingProfile: boolean;
  isLoadingAwards: boolean;
  watched: boolean;
  watchPending: boolean;
  onToggleWatch: () => void;
}

function Metric({
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
    <div className="min-w-0 p-4">
      <dt className="text-muted-foreground text-[11px] font-semibold tracking-[0.12em] uppercase">{label}</dt>
      <dd className="mt-1.5 truncate text-xl font-semibold tracking-tight tabular-nums" title={value}>
        {value}
      </dd>
      <p className="text-muted-foreground mt-1 min-h-5 text-xs leading-5">
        {delta == null ? (
          detail
        ) : (
          <span className="inline-flex items-center gap-1">
            <DeltaIcon className="h-3.5 w-3.5" aria-hidden="true" />
            {delta >= 0 ? "+" : ""}
            {formatPercent(delta)} vs. periodo anterior
          </span>
        )}
      </p>
    </div>
  );
}

function AwardsPreview({ data, loading }: { data?: CompanyAwardsData; loading: boolean }) {
  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }, (_, index) => (
          <Skeleton key={index} className="h-20 w-full rounded-md" />
        ))}
      </div>
    );
  }

  if (!data?.items.length) {
    return (
      <p className="text-muted-foreground rounded-lg border border-dashed p-5 text-center text-sm">
        No hay adjudicaciones dentro del ámbito seleccionado.
      </p>
    );
  }

  return (
    <div className="divide-y overflow-hidden rounded-lg border">
      {data.items.slice(0, 5).map((award) => (
        <Link
          key={award.licitacion_id}
          href={`/detalle?lic=${encodeURIComponent(award.licitacion_id)}`}
          className="hover:bg-muted/45 focus-visible:ring-ring group block p-3.5 transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset"
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p
                className="group-hover:text-primary truncate text-sm font-medium"
                title={award.titulo ?? award.licitacion_id}
              >
                {truncate(award.titulo ?? award.licitacion_id, 84)}
              </p>
              <p className="text-muted-foreground mt-1 truncate text-xs" title={award.organo_contratacion ?? undefined}>
                {formatDate(award.fecha_adjudicacion)} · {award.organo_contratacion || "Órgano sin identificar"}
              </p>
            </div>
            <div className="shrink-0 text-right">
              <p className="text-sm font-semibold tabular-nums">{formatCurrency(award.importe_adjudicado)}</p>
              <p className="text-muted-foreground mt-1 text-xs tabular-nums">
                {award.baja_pct == null ? "Baja -" : `Baja ${formatPercent(award.baja_pct)}`}
                {award.n_ofertas_recibidas == null ? "" : ` · ${formatNumber(award.n_ofertas_recibidas)} ofertas`}
              </p>
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}

export function CompanyQuickView({
  empresaId,
  groupIds,
  company,
  profile,
  recentAwards,
  isLoadingProfile,
  isLoadingAwards,
  watched,
  watchPending,
  onToggleWatch,
}: CompanyQuickViewProps) {
  const totals = profile?.totales;
  const comparison = profile?.comparacion;
  const position = profile?.posicion_mercado;
  const awardCount = totals?.contratos ?? company.count;
  const awardedAmount = totals?.importe_total ?? company.importe;
  const averageTicket = awardCount ? awardedAmount / awardCount : company.importe_medio;
  const fullProfileHref =
    groupIds && groupIds.length > 1
      ? `/competidores/empresa/${empresaId}?ids=${groupIds.join(",")}`
      : `/competidores/empresa/${empresaId}`;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-col space-y-2 border-b px-5 py-5 pr-14 text-left md:px-6">
        <div className="flex flex-wrap items-center gap-2">
          {company.nif ? <Badge variant="outline">NIF {company.nif}</Badge> : null}
          {profile?.empresa.es_ute ? <Badge variant="info">UTE</Badge> : null}
          {profile?.empresa.grupo ? <Badge variant="secondary">Grupo {profile.empresa.grupo}</Badge> : null}
        </div>
        <h2 className="mt-2 text-xl leading-tight font-semibold text-foreground md:text-2xl">{company.nombre}</h2>
        <p className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="inline-flex items-center gap-1.5">
            <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
            Última adjudicación: {formatDate(totals?.ultima_adjudicacion)}
          </span>
          {profile?.actividad_historica.primera_adjudicacion ? (
            <span>En contratación pública desde {formatDate(profile.actividad_historica.primera_adjudicacion)}</span>
          ) : null}
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5 md:px-6">
        {isLoadingProfile ? (
          <>
            <Skeleton className="h-24 w-full rounded-lg" />
            <div className="grid grid-cols-2 overflow-hidden rounded-lg border">
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton key={index} className="m-4 h-20" />
              ))}
            </div>
            <Skeleton className="h-52 w-full rounded-lg" />
          </>
        ) : (
          <>
            {profile ? (
              <section className="border-primary/50 bg-primary/[0.035] rounded-lg border-l-4 px-4 py-3.5">
                <h3 className="text-xs font-semibold tracking-[0.12em] uppercase">Cómo opera</h3>
                <p className="text-muted-foreground mt-1.5 text-sm leading-6">{buildExecutiveSummary(profile)}</p>
              </section>
            ) : null}

            <section aria-labelledby="quick-kpis-title">
              <div className="mb-2 flex items-center justify-between gap-3">
                <h3 id="quick-kpis-title" className="text-sm font-semibold">
                  Operativa en cifras
                </h3>
                <span className="text-muted-foreground text-xs">Ámbito de filtros actual</span>
              </div>
              <dl className="bg-card grid grid-cols-2 overflow-hidden rounded-lg border sm:grid-cols-3 [&>*]:border-r [&>*]:border-b [&>*:nth-child(2n)]:border-r-0 sm:[&>*:nth-child(2n)]:border-r sm:[&>*:nth-child(3n)]:border-r-0 [&>*:nth-last-child(-n+2)]:border-b-0 sm:[&>*:nth-last-child(-n+3)]:border-b-0">
                <Metric
                  label="Importe adjudicado"
                  value={formatCurrency(awardedAmount)}
                  detail="Volumen acumulado"
                  delta={comparison?.variacion_importe_pct}
                />
                <Metric
                  label="Adjudicaciones"
                  value={formatNumber(awardCount)}
                  detail="Expedientes ganados"
                  delta={comparison?.variacion_contratos_pct}
                />
                <Metric
                  label="Cuota y posición"
                  value={`${formatPercent(position?.cuota_pct ?? company.cuota)}${position?.rank ? ` · #${position.rank}` : ""}`}
                  detail={position ? `entre ${formatNumber(position.empresas)} empresas` : "Cuota del mercado filtrado"}
                />
                <Metric
                  label="Contrato típico"
                  value={formatCurrency(totals?.importe_mediano ?? averageTicket)}
                  detail={totals?.importe_mediano != null ? "Mediana adjudicada" : "Importe medio adjudicado"}
                />
                <Metric
                  label="Baja media"
                  value={formatPercent(totals?.baja_media_pct ?? company.baja_media)}
                  detail="Descuento sobre presupuesto"
                />
                <Metric
                  label="Presión competitiva"
                  value={
                    totals?.ofertas_medias == null && company.ofertas_medias == null
                      ? "-"
                      : `${(totals?.ofertas_medias ?? company.ofertas_medias)?.toFixed(1)} ofertas`
                  }
                  detail={
                    totals
                      ? `Cobertura del dato: ${formatPercent(totals.cobertura_ofertas_pct, 0)}`
                      : "Ofertas recibidas de media"
                  }
                />
              </dl>
              {totals ? (
                <div className="text-muted-foreground mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                  <span>{formatNumber(totals.organos)} clientes públicos</span>
                  <span>{formatNumber(totals.territorios)} territorios</span>
                  <span>{formatNumber(totals.familias_cpv)} familias CPV</span>
                  <span>{formatPercent(totals.pct_oferta_unica)} con oferta única</span>
                </div>
              ) : null}
            </section>

            {profile?.por_anio.length ? (
              <section aria-labelledby="quick-trend-title">
                <div className="mb-3">
                  <h3 id="quick-trend-title" className="text-sm font-semibold">
                    Progreso anual
                  </h3>
                  <p className="text-muted-foreground mt-0.5 text-xs">
                    Importe adjudicado y número de contratos por año
                  </p>
                </div>
                <div className="rounded-lg border p-4">
                  <CompanyYearTrend rows={profile.por_anio} compact />
                </div>
              </section>
            ) : null}
          </>
        )}

        <section aria-labelledby="quick-awards-title">
          <div className="mb-3 flex items-end justify-between gap-4">
            <div>
              <h3 id="quick-awards-title" className="text-sm font-semibold">
                Adjudicaciones recientes
              </h3>
              <p className="text-muted-foreground mt-0.5 text-xs">
                Los expedientes que explican la actividad más reciente
              </p>
            </div>
            {recentAwards?.total ? (
              <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                {formatNumber(recentAwards.total)} en total
              </span>
            ) : null}
          </div>
          <AwardsPreview data={recentAwards} loading={isLoadingAwards} />
        </section>
      </div>

      <div className="bg-background/95 supports-[backdrop-filter]:bg-background/85 flex flex-col-reverse gap-2 border-t p-4 backdrop-blur sm:flex-row sm:items-center sm:justify-between md:px-6">
        <Button variant={watched ? "secondary" : "outline"} onClick={onToggleWatch} disabled={watchPending}>
          <Eye aria-hidden="true" />
          {watched ? "Vigilando" : "Vigilar empresa"}
        </Button>
        <Link href={fullProfileHref} className={cn(buttonVariants(), "min-h-10 gap-2")}>
          Ver análisis y listado completo
          <ExternalLink aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
}
