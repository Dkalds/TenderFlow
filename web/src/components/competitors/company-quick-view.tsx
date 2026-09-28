"use client";

import Link from "next/link";

import {
  PanelEmpty,
  SUPERFICIE_PANEL,
  SectionTitle,
  StatCell,
  StatStrip,
  TONO_PANEL,
} from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { SeguirBoton } from "@/components/seguir-boton";
import { Skeleton } from "@/components/ui/skeleton";
import { Pista } from "@/components/ui/pista";
import { cn, EMPTY, formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/utils";

import { CompanyYearTrend } from "./company-year-trend";
import {
  buildExecutiveSummary,
  variacionFrenteAnterior,
  type CompanyAwardsData,
  type CompanyProfileData,
} from "./company-profile-types";

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
      <PanelEmpty
        size="sm"
        title="Sin adjudicaciones recientes"
        hint="No hay adjudicaciones dentro del ámbito seleccionado."
      />
    );
  }

  return (
    <div className="divide-y divide-border/60 overflow-hidden rounded-md border border-border/60">
      {data.items.slice(0, 5).map((award) => (
        <Link
          key={award.licitacion_id}
          href={`/detalle?lic=${encodeURIComponent(award.licitacion_id)}`}
          className="group block p-3.5 transition-colors hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              {/* Dentro de un enlace: la `Pista` no añade foco y el nombre del
                  enlace ya es el título entero (el recorte es CSS). */}
              <Pista contenido={award.titulo ?? award.licitacion_id}>
                <p className="truncate text-tf-body font-medium transition-colors group-hover:text-primary">
                  {award.titulo ?? award.licitacion_id}
                </p>
              </Pista>
              <Pista contenido={award.organo_contratacion}>
                <p className="mt-1 truncate text-tf-meta text-muted-foreground">
                  {formatDate(award.fecha_adjudicacion)} · {award.organo_contratacion || "Órgano sin identificar"}
                </p>
              </Pista>
            </div>
            <div className="shrink-0 text-right">
              <p className="text-tf-body font-semibold">{formatCurrency(award.importe_adjudicado)}</p>
              <p className="mt-1 text-tf-meta text-muted-foreground">
                {award.baja_pct == null ? `Baja ${EMPTY}` : `Baja ${formatPercent(award.baja_pct)}`}
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
}: CompanyQuickViewProps) {
  const totals = profile?.totales;
  const comparison = profile?.comparacion;
  const position = profile?.posicion_mercado;
  const awardCount = totals?.contratos ?? company.count;
  const awardedAmount = totals?.importe_total ?? company.importe;
  const averageTicket = awardCount ? awardedAmount / awardCount : company.importe_medio;
  const fullProfileHref =
    groupIds && groupIds.length > 1
      ? `/competencia/empresa/${empresaId}?ids=${groupIds.join(",")}`
      : `/competencia/empresa/${empresaId}`;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-col space-y-2 border-b border-border/60 px-4 py-4 text-left">
        <div className="flex flex-wrap items-center gap-2">
          {company.nif ? (
            <Badge variant="outline">
              NIF <span className="font-mono">{company.nif}</span>
            </Badge>
          ) : null}
          {profile?.empresa.es_ute ? <Badge variant="info">UTE</Badge> : null}
          {profile?.empresa.grupo ? <Badge variant="secondary">Grupo {profile.empresa.grupo}</Badge> : null}
        </div>
        <h2 className="mt-1 font-display text-tf-title text-foreground">{company.nombre}</h2>
        <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-tf-meta text-muted-foreground">
          <span>Última adjudicación: {formatDate(totals?.ultima_adjudicacion)}</span>
          {profile?.actividad_historica.primera_adjudicacion ? (
            <span>En contratación pública desde {formatDate(profile.actividad_historica.primera_adjudicacion)}</span>
          ) : null}
        </p>
      </div>

      <div className="relative min-h-0 flex-1 space-y-6 overflow-y-auto px-4 py-4">
        {isLoadingProfile ? (
          <>
            <Skeleton className="h-24 w-full rounded-xl" />
            <Skeleton className="h-52 w-full rounded-xl" />
            <Skeleton className="h-52 w-full rounded-xl" />
          </>
        ) : (
          <>
            {profile ? (
              <section className={cn(SUPERFICIE_PANEL, TONO_PANEL.accent, "px-4 py-3.5")}>
                <h3 className="text-tf-body font-semibold">Cómo opera</h3>
                <p className="mt-1.5 text-tf-body text-muted-foreground">{buildExecutiveSummary(profile)}</p>
              </section>
            ) : null}

            <section aria-labelledby="quick-kpis-title">
              <SectionTitle as="h3" id="quick-kpis-title" hint="Ámbito de filtros actual">
                Operativa en cifras
              </SectionTitle>
              <StatStrip columns={2}>
                <StatCell
                  label="Importe adjudicado"
                  value={formatCurrency(awardedAmount)}
                  hint={variacionFrenteAnterior(comparison?.variacion_importe_pct, "Volumen acumulado")}
                />
                <StatCell
                  label="Adjudicaciones"
                  value={formatNumber(awardCount)}
                  hint={variacionFrenteAnterior(comparison?.variacion_contratos_pct, "Expedientes ganados")}
                />
                <StatCell
                  label="Cuota y posición"
                  value={`${formatPercent(position?.cuota_pct ?? company.cuota)}${position?.rank ? ` · #${position.rank}` : ""}`}
                  hint={position ? `Entre ${formatNumber(position.empresas)} empresas` : "Cuota del mercado filtrado"}
                />
                <StatCell
                  label="Contrato típico"
                  value={formatCurrency(totals?.importe_mediano ?? averageTicket)}
                  hint={totals?.importe_mediano != null ? "Mediana adjudicada" : "Importe medio adjudicado"}
                />
                <StatCell
                  label="Baja media"
                  value={formatPercent(totals?.baja_media_pct ?? company.baja_media)}
                  hint="Descuento sobre presupuesto"
                />
                <StatCell
                  label="Presión competitiva"
                  value={
                    totals?.ofertas_medias == null && company.ofertas_medias == null
                      ? EMPTY
                      : `${(totals?.ofertas_medias ?? company.ofertas_medias)?.toFixed(1).replace(".", ",")} ofertas`
                  }
                  hint={
                    totals
                      ? `Cobertura del dato: ${formatPercent(totals.cobertura_ofertas_pct, 0)}`
                      : "Ofertas recibidas de media"
                  }
                />
              </StatStrip>
              {totals ? (
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-tf-meta text-muted-foreground">
                  <span>{formatNumber(totals.organos)} clientes públicos</span>
                  <span>{formatNumber(totals.territorios)} territorios</span>
                  <span>{formatNumber(totals.familias_cpv)} familias CPV</span>
                  <span>{formatPercent(totals.pct_oferta_unica)} con oferta única</span>
                </div>
              ) : null}
            </section>

            {profile?.por_anio.length ? (
              <section aria-labelledby="quick-trend-title">
                <SectionTitle as="h3" id="quick-trend-title" hint="Importe y contratos por año">
                  Progreso anual
                </SectionTitle>
                <div className="rounded-md border border-border/60 p-4">
                  <CompanyYearTrend rows={profile.por_anio} compact />
                </div>
              </section>
            ) : null}
          </>
        )}

        <section aria-labelledby="quick-awards-title">
          <SectionTitle
            as="h3"
            id="quick-awards-title"
            hint={recentAwards?.total ? `${formatNumber(recentAwards.total)} en total` : undefined}
          >
            Adjudicaciones recientes
          </SectionTitle>
          <AwardsPreview data={recentAwards} loading={isLoadingAwards} />
        </section>
      </div>

      <div className="flex flex-col-reverse gap-2 border-t border-border/60 bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
        {/* El control único de ADR-031 §C con la piel del botón de siempre.
            Sigue el grupo entero de identidades equivalentes: vigilar una
            empresa deduplicada es vigilar todos sus `empresa_id`. */}
        <SeguirBoton
          targetType="empresa"
          targetId={String(empresaId)}
          equivalentes={(groupIds && groupIds.length > 0 ? groupIds : [empresaId]).map(String)}
          icono="ojo"
          nombreAccesible="visible"
          textos={{ seguir: "Vigilar empresa", siguiendo: "Vigilando" }}
          clases={{
            base: "",
            activo: buttonVariants({ variant: "secondary", size: "sm" }),
            inactivo: buttonVariants({ variant: "outline", size: "sm" }),
          }}
        />
        <Link href={fullProfileHref} className={buttonVariants({ size: "sm" })}>
          Ver análisis y listado completo
        </Link>
      </div>
    </div>
  );
}
