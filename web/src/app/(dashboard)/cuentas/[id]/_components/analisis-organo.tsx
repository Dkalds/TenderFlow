"use client";

/**
 * El análisis de Mercado › Órganos, órgano a órgano, dentro de la ficha.
 *
 * F1.5 pedía en la ficha el lead-time medio «ya calculado» y la estacionalidad:
 * los calcula el detalle de órgano de Mercado (`GET /analytics/organos/{organo}`)
 * y aquí se pide exactamente ese, con la misma clave de caché que usa Mercado,
 * en vez de sumar en el cliente las cifras de varios órganos —que sería
 * fabricar un agregado que la API no dio (ADR-014)—. Por eso va de uno en
 * uno, con un selector cuando la cuenta tiene varios.
 */

import * as React from "react";
import dynamic from "next/dynamic";

import {
  EnlaceIr,
  Panel,
  PanelEmpty,
  PanelError,
  PanelTitle,
  SectionTitle,
  StatCell,
  StatStrip,
} from "@/components/console/panel";
import { Field } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import type { Schemas } from "@/lib/api-types";
import type { CuentaOrgano } from "@/hooks/use-cuentas";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

const OrganosAdjudicatariosChart = dynamic(
  () => import("@/components/charts/organos-charts").then((m) => ({ default: m.OrganosAdjudicatariosChart })),
  { ssr: false, loading: () => <Skeleton className="h-[280px] w-full rounded-md" /> },
);
const OrganosEstacionalidadChart = dynamic(
  () => import("@/components/charts/organos-charts").then((m) => ({ default: m.OrganosEstacionalidadChart })),
  { ssr: false, loading: () => <Skeleton className="h-[200px] w-full rounded-md" /> },
);

type DetalleOrgano = Schemas["OrganoDetailResult"];

export function AnalisisOrgano({ organos }: { organos: readonly CuentaOrgano[] }) {
  const [elegido, setElegido] = React.useState(organos[0]?.organo_nombre ?? "");
  const id = React.useId();
  // Si el órgano elegido deja de ser de la cuenta, se vuelve al primero.
  const organo = organos.some((o) => o.organo_nombre === elegido)
    ? elegido
    : (organos[0]?.organo_nombre ?? "");

  const { data, isLoading, error, refetch } = useFilteredQuery<DetalleOrgano>(
    ["analytics", "organo-detail", organo],
    `/api/v1/analytics/organos/${encodeURIComponent(organo)}`,
    { enabled: Boolean(organo), staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
    undefined,
    true,
  );
  const kpis = data?.kpis;

  return (
    <Panel>
      <PanelTitle
        as="h2"
        title="Análisis por órgano"
        actions={
          organo ? (
            <EnlaceIr href={`/mercado?vista=organos&organo_q=${encodeURIComponent(organo)}`}>
              Abrir en Mercado
            </EnlaceIr>
          ) : undefined
        }
      />
      <p className="-mt-1.5 mb-3 text-tf-meta text-muted-foreground">
        Las cifras de Mercado › Órganos para un órgano, sin filtros de ámbito. No se suman entre
        órganos: cada uno se mide sobre su propio histórico.
      </p>

      {organos.length > 1 && (
        <Field htmlFor={`${id}-organo`} label="Órgano" className="mb-3">
          <select
            id={`${id}-organo`}
            value={organo}
            onChange={(event) => setElegido(event.target.value)}
            className="h-9 w-full rounded-md border border-input bg-background px-2 text-tf-body"
          >
            {organos.map((o) => (
              <option key={o.id} value={o.organo_nombre}>
                {o.organo_nombre}
              </option>
            ))}
          </select>
        </Field>
      )}

      {error ? (
        <PanelError
          title="No se pudo cargar el análisis del órgano"
          error={error}
          onRetry={() => void refetch()}
          height={120}
        />
      ) : !isLoading && (!kpis || kpis.total_licitaciones === 0) ? (
        <PanelEmpty size="sm" hint="Mercado no tiene histórico de este órgano." />
      ) : (
        <div className="flex flex-col gap-4">
          {/* La tira sale ya con sus rótulos mientras llegan las cifras: el
              esqueleto tiene la forma del dato y la ficha no salta. */}
          <StatStrip columns={4}>
            <StatCell
              label="Licitaciones"
              value={kpis ? formatNumber(kpis.total_licitaciones) : EMPTY}
              loading={isLoading}
            />
            <StatCell
              label="Importe total"
              value={kpis ? formatCurrency(kpis.importe_total) : EMPTY}
              hint={kpis && kpis.importe_medio > 0 ? `Medio: ${formatCurrency(kpis.importe_medio)}` : undefined}
              loading={isLoading}
            />
            <StatCell
              label="Adjudicado"
              value={kpis ? formatPercent(kpis.pct_adjudicado) : EMPTY}
              hint="De las licitaciones del órgano"
              loading={isLoading}
            />
            <StatCell
              label="Días hasta adjudicar (mediana)"
              value={kpis?.lead_time_medio != null ? `${Math.round(kpis.lead_time_medio)} días` : EMPTY}
              hint="De la publicación a la adjudicación"
              loading={isLoading}
            />
          </StatStrip>
          {!isLoading && (
            <div className="grid gap-4 lg:grid-cols-2">
              {(data?.top_adjudicatarios?.length ?? 0) > 0 && (
                <section>
                  <SectionTitle as="h3">Quién gana aquí</SectionTitle>
                  <OrganosAdjudicatariosChart data={data?.top_adjudicatarios ?? []} />
                </section>
              )}
              {(data?.estacionalidad?.length ?? 0) > 0 && (
                <section>
                  <SectionTitle as="h3">Cuándo publica</SectionTitle>
                  <OrganosEstacionalidadChart data={data?.estacionalidad ?? []} />
                </section>
              )}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
