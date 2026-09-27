"use client";

import {
  Panel,
  PanelTitle,
  SUPERFICIE_PANEL,
  StatCell,
  StatStrip,
  TONO_PANEL,
} from "@/components/console/panel";
import { Pista } from "@/components/ui/pista";
import { cn, EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import { CompanyCortes } from "./company-cortes";
import { CompanyUteParticipations } from "./company-ute-participations";
import { CompanyYearTrend } from "./company-year-trend";
import {
  buildExecutiveSummary,
  cpvFamilyLabel,
  variacionFrenteAnterior,
  type CompanyBreakdown,
  type CompanyProfileData,
} from "./company-profile-types";

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
    <section className="min-w-0 p-4" aria-label={title}>
      <h3 className="text-tf-body font-semibold">{title}</h3>
      <p className="mt-0.5 text-tf-meta text-muted-foreground">{description}</p>
      {rows.length ? (
        <div className="mt-4 space-y-4">
          {rows.slice(0, 5).map((row, index) => {
            const label = cpv ? cpvFamilyLabel(row.codigo) : row.label;
            return (
              <div key={`${row.codigo ?? row.label}-${index}`} className="space-y-1.5">
                <div className="flex items-start justify-between gap-3 text-tf-body">
                  <div className="min-w-0">
                    <Pista contenido={label}>
                      <p className="truncate font-medium">{label}</p>
                    </Pista>
                    <p className="text-tf-meta text-muted-foreground">{formatNumber(row.contratos)} adjudicaciones</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="font-medium">{formatCurrency(row.importe)}</p>
                    <p className="text-tf-meta text-muted-foreground">{formatPercent(row.cuota_empresa_pct, 0)}</p>
                  </div>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                  <div
                    className="h-full rounded-full bg-primary"
                    style={{ width: `${Math.max(2, row.cuota_empresa_pct)}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="py-10 text-center text-tf-meta text-muted-foreground">{empty}</p>
      )}
    </section>
  );
}

/** Punto de tono de un movimiento: el tono es información, así que se queda. */
function tonoPunto(tone: string): string {
  if (tone === "positive") return "bg-success";
  if (tone === "warning") return "bg-warning";
  if (tone === "negative") return "bg-destructive";
  return "bg-muted-foreground/40";
}

export function CompanyProfileSummary({ profile }: { profile: CompanyProfileData }) {
  const totals = profile.totales;
  const position = profile.posicion_mercado;
  const comparison = profile.comparacion;

  return (
    <div className="space-y-6">
      <section
        className={cn(SUPERFICIE_PANEL, TONO_PANEL.accent, "px-5 py-4")}
        aria-labelledby="profile-reading-title"
      >
        <h2 id="profile-reading-title" className="text-tf-body font-semibold">
          Perfil operativo
        </h2>
        <p className="mt-1.5 max-w-5xl text-tf-body text-muted-foreground">{buildExecutiveSummary(profile)}</p>
      </section>

      <section aria-labelledby="profile-kpis-title">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 id="profile-kpis-title" className="text-tf-lede">
              Operativa en cifras
            </h2>
            <p className="mt-0.5 text-tf-meta text-muted-foreground">Tamaño, ritmo, posición y presión competitiva</p>
          </div>
          <p className="text-tf-meta text-muted-foreground">Datos del periodo seleccionado</p>
        </div>

        <StatStrip columns={3}>
          <StatCell
            label="Importe adjudicado"
            value={formatCurrency(totals.importe_total)}
            hint={variacionFrenteAnterior(comparison.variacion_importe_pct, "Volumen acumulado")}
          />
          <StatCell
            label="Adjudicaciones"
            value={formatNumber(totals.contratos)}
            hint={variacionFrenteAnterior(comparison.variacion_contratos_pct, "Expedientes ganados")}
          />
          <StatCell
            label="Cuota y posición"
            value={`${formatPercent(position.cuota_pct)}${position.rank ? ` · #${position.rank}` : ""}`}
            hint={position.rank ? `Entre ${formatNumber(position.empresas)} empresas` : "Sin posición calculable"}
          />
          <StatCell
            label="Contrato típico"
            value={formatCurrency(totals.importe_mediano)}
            hint="Mediana adjudicada: pesa menos lo extremo"
          />
          <StatCell
            label="Baja media"
            value={formatPercent(totals.baja_media_pct)}
            hint="Descuento sobre el presupuesto de licitación"
          />
          <StatCell
            label="Presión competitiva"
            value={
              totals.ofertas_medias == null
                ? EMPTY
                : `${totals.ofertas_medias.toFixed(1).replace(".", ",")} ofertas`
            }
            hint={`Cobertura del dato: ${formatPercent(totals.cobertura_ofertas_pct, 0)}`}
          />
        </StatStrip>

        <StatStrip columns={4} className="mt-3">
          <StatCell label="Clientes públicos" value={formatNumber(totals.organos)} />
          <StatCell label="Territorios" value={formatNumber(totals.territorios)} />
          <StatCell label="Familias CPV" value={formatNumber(totals.familias_cpv)} />
          <StatCell label="Adjudicaciones con oferta única" value={formatPercent(totals.pct_oferta_unica)} />
        </StatStrip>
      </section>

      <CompanyUteParticipations participations={profile.participaciones_ute} companyName={profile.empresa.nombre} />

      <Panel>
        <PanelTitle title="Progreso anual" hint="Importe adjudicado y contratos ganados por ejercicio" />
        <CompanyYearTrend rows={profile.por_anio} />
      </Panel>

      <Panel className="p-0">
        <PanelTitle
          className="mb-0 px-4 pt-3.5"
          title="Dónde y para quién opera"
          hint="Especialización, compradores recurrentes y huella territorial"
        />
        <div className="grid divide-y divide-border/60 xl:grid-cols-3 xl:divide-x xl:divide-y-0">
          <BreakdownColumn
            title="Especialización"
            description="Familias CPV por peso económico"
            rows={profile.por_cpv}
            empty="Sin CPV clasificado"
            cpv
          />
          <BreakdownColumn
            title="Clientes principales"
            description={`Los 3 primeros: ${formatPercent(profile.concentracion_clientes.top3_importe_pct, 0)} del importe`}
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
        <p className="border-t border-border/60 px-4 py-3 text-tf-meta text-muted-foreground">
          Dependencia del primer cliente: {formatPercent(profile.concentracion_clientes.top1_importe_pct)} del
          importe. La cobertura del número de ofertas es del {formatPercent(totals.cobertura_ofertas_pct)}.
        </p>
      </Panel>

      {(profile.por_procedimiento?.length ?? 0) + (profile.por_tramo_importe?.length ?? 0) > 0 ? (
        <Panel className="p-0">
          <PanelTitle
            className="mb-0 px-4 pt-3.5"
            title="Procedimiento y tamaño"
            hint={`Dónde gana y con qué baja. Sin media por debajo de ${profile.corte_min_n ?? 5} adjudicaciones por celda.`}
          />
          <CompanyCortes
            porProcedimiento={profile.por_procedimiento ?? []}
            porTramo={profile.por_tramo_importe ?? []}
            minimo={profile.corte_min_n ?? 5}
          />
        </Panel>
      ) : null}

      {profile.movimientos.length ? (
        <section aria-labelledby="movements-title">
          <div className="mb-3">
            <h2 id="movements-title" className="text-tf-lede">
              Cambios relevantes
            </h2>
            <p className="mt-0.5 text-tf-meta text-muted-foreground">
              Señales que ayudan a interpretar el progreso reciente
            </p>
          </div>
          <ul className={cn(SUPERFICIE_PANEL, "divide-y divide-border/60 overflow-hidden")}>
            {profile.movimientos.slice(0, 4).map((movement, index) => (
              <li key={`${movement.kind}-${index}`} className="flex gap-2.5 px-4 py-3.5">
                <span
                  aria-hidden="true"
                  className={cn("mt-1.5 size-2 flex-none rounded-full", tonoPunto(movement.tone))}
                />
                <div className="min-w-0">
                  <p className="text-tf-body font-medium">{movement.title}</p>
                  <p className="mt-0.5 text-tf-body text-muted-foreground">{movement.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
