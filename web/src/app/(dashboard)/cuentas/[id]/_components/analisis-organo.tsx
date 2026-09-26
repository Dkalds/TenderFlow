"use client";

/**
 * El análisis de Mercado → Órganos, órgano a órgano, dentro de la ficha.
 *
 * F1.5 pedía en la ficha el lead-time medio «ya calculado» y la estacionalidad:
 * los calcula el detalle de órgano de Mercado (`GET /analytics/organos/{organo}`)
 * y aquí se pide exactamente ese, con la misma clave de caché que usa Mercado,
 * en vez de sumar en el cliente las cifras de varios órganos —que sería
 * fabricar un agregado que el backend no dio (ADR-014)—. Por eso va de uno en
 * uno, con un selector cuando la cuenta tiene varios.
 */

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { Clock, Hash, TrendingUp, Trophy } from "lucide-react";

import { KpiCard } from "@/components/charts/kpi-card";
import { Panel, PanelEmpty, PanelError, SectionTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import type { Schemas } from "@/lib/api-types";
import type { CuentaOrgano } from "@/hooks/use-cuentas";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

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

  const { data, isLoading, isError, refetch } = useFilteredQuery<DetalleOrgano>(
    ["analytics", "organo-detail", organo],
    `/api/v1/analytics/organos/${encodeURIComponent(organo)}`,
    { enabled: Boolean(organo), staleTime: 5 * 60 * 1000 },
    undefined,
    true,
  );
  const kpis = data?.kpis;

  return (
    <Panel>
      <SectionTitle
        aside={
          organo ? (
            <Link
              href={`/mercado?vista=organos&organo_q=${encodeURIComponent(organo)}`}
              className="text-tf-micro text-muted-foreground hover:text-foreground hover:underline"
            >
              Abrir en Mercado
            </Link>
          ) : undefined
        }
      >
        Análisis por órgano
      </SectionTitle>
      <p className="-mt-1 mb-3 text-tf-micro leading-relaxed text-muted-foreground">
        Las cifras de Mercado → Órganos para un órgano, sin filtros de ámbito. No se suman entre
        órganos: cada uno se mide sobre su propio histórico.
      </p>

      {organos.length > 1 && (
        <div className="mb-3 flex flex-col gap-1.5">
          <label htmlFor={`${id}-organo`} className="text-xs font-medium">
            Órgano
          </label>
          <select
            id={`${id}-organo`}
            value={organo}
            onChange={(event) => setElegido(event.target.value)}
            className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
          >
            {organos.map((o) => (
              <option key={o.id} value={o.organo_nombre}>
                {o.organo_nombre}
              </option>
            ))}
          </select>
        </div>
      )}

      {isLoading ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : isError ? (
        <PanelError
          title="No se pudo cargar el análisis del órgano"
          onRetry={() => void refetch()}
          height={120}
        />
      ) : !kpis || kpis.total_licitaciones === 0 ? (
        <PanelEmpty message="Mercado no tiene histórico de este órgano." height={96} />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <KpiCard title="Licitaciones" value={formatNumber(kpis.total_licitaciones)} icon={Hash} />
            <KpiCard
              title="Importe total"
              value={formatCurrency(kpis.importe_total)}
              subtitle={kpis.importe_medio > 0 ? `medio ${formatCurrency(kpis.importe_medio)}` : undefined}
              icon={TrendingUp}
            />
            <KpiCard
              title="% adjudicado"
              value={formatPercent(kpis.pct_adjudicado)}
              subtitle="del total del órgano"
              icon={Trophy}
            />
            <KpiCard
              title="Lead time mediano"
              value={kpis.lead_time_medio != null ? `${Math.round(kpis.lead_time_medio)} días` : "— d"}
              subtitle="de la publicación a la adjudicación"
              icon={Clock}
            />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            {(data?.top_adjudicatarios?.length ?? 0) > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium">Quién gana aquí</p>
                <OrganosAdjudicatariosChart data={data?.top_adjudicatarios ?? []} />
              </div>
            )}
            {(data?.estacionalidad?.length ?? 0) > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium">Cuándo publica</p>
                <OrganosEstacionalidadChart data={data?.estacionalidad ?? []} />
              </div>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
