"use client";

/**
 * Panel del órgano abierto.
 *
 * Era un Sheet modal que tapaba el ranking del que venías, justo cuando lo que
 * quieres es comparar dos órganos. Ahora vive en el mismo plano y el ranking
 * sigue ahí para saltar al siguiente.
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { startTransition } from "react";
import { X } from "lucide-react";

import {
  PanelEmpty,
  PanelError,
  PanelLoading,
  SectionTitle,
  StatCell,
  StatStrip,
} from "@/components/console/panel";
import { SeguirBoton } from "@/components/seguir-boton";
import { Skeleton } from "@/components/ui/skeleton";
import { useCuentaDeOrgano } from "@/hooks/use-cuentas";
import { usePuedeEscribir } from "@/hooks/use-organization";
import { EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import type { OrganoDetailResponse } from "../_hooks/use-organos-view";
import { OrganoTopScored } from "./organo-top-scored";

const OrganosAdjudicatariosChart = dynamic(() => import("@/components/charts/organos-charts").then(m => ({ default: m.OrganosAdjudicatariosChart })), { ssr: false, loading: () => <PanelLoading height={280} /> });
const OrganosEstacionalidadChart = dynamic(() => import("@/components/charts/organos-charts").then(m => ({ default: m.OrganosEstacionalidadChart })), { ssr: false, loading: () => <PanelLoading height={200} /> });

/** Lo que ve un `viewer` en lugar de la campana: de qué cuenta es el órgano. */
function CuentaSoloLectura({ organo }: { organo: string }) {
  const { data: cuenta } = useCuentaDeOrgano(organo);
  if (!cuenta) return null;
  return (
    <Link
      href={`/cuentas/${cuenta.id}`}
      className="max-w-[10rem] flex-none truncate rounded-md border border-border/60 px-1.5 py-0.5 text-tf-micro text-muted-foreground transition-colors hover:text-foreground"
    >
      Cuenta: {cuenta.nombre}
    </Link>
  );
}

export function OrganoDetalle({
  organo,
  detalle,
  isLoading,
  error,
  onRetry,
  onClose,
}: {
  organo: string;
  detalle: OrganoDetailResponse | undefined;
  isLoading: boolean;
  /** El fallo de la consulta del órgano: se dice, no se disfraza de «sin datos». */
  error?: unknown;
  onRetry?: () => void;
  onClose: () => void;
}) {
  const puedeEscribir = usePuedeEscribir();
  const kpis = detalle?.kpis;
  return (
    <aside
      aria-label={`Detalle de ${organo}`}
      className="hidden w-[420px] flex-none flex-col overflow-hidden rounded-xl border border-border/60 bg-card xl:flex"
    >
      <div className="flex flex-none items-start gap-2 border-b border-border/60 px-3.5 py-2.5">
        <h2 className="min-w-0 flex-1 text-tf-body font-semibold leading-tight">{organo}</h2>
        {/* F1.5 / ADR-031 §C — el control único «Seguir», que para un órgano
            crea o completa la cuenta objetivo de la organización activa
            (`/cuentas`), con sus avisos de publicación y de vencimiento para
            todo el equipo. Es la acción que declara «este cliente me interesa
            aunque hoy no publique nada». Un `viewer` no puede seguir: en vez
            de un botón que siempre le fallaría, ve de qué cuenta es. */}
        {puedeEscribir ? (
          <SeguirBoton
            targetType="organo"
            targetId={organo}
            etiqueta={`el órgano ${organo}`}
            variante="icono"
            className="flex-none"
          />
        ) : (
          <CuentaSoloLectura organo={organo} />
        )}
        <button
          type="button"
          aria-label="Cerrar detalle del órgano"
          onClick={() => startTransition(onClose)}
          className="tf-pressable grid h-6 w-6 flex-none place-items-center rounded-md border border-border/60 text-muted-foreground hover:text-foreground"
        >
          <X className="h-3 w-3" aria-hidden="true" />
        </button>
      </div>
      <div className="relative min-h-0 flex-1 overflow-y-auto px-3.5 pb-4">
        {isLoading ? (
          <div className="mt-4 space-y-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : error ? (
          <PanelError
            className="mt-4"
            title="No se pudo cargar el órgano"
            error={error}
            onRetry={onRetry}
          />
        ) : detalle && kpis ? (
          <div className="mt-4 space-y-6">
            <StatStrip columns={2}>
              <StatCell label="Licitaciones" value={formatNumber(kpis.total_licitaciones)} />
              <StatCell
                label="Importe total"
                value={formatCurrency(kpis.importe_total)}
                hint={kpis.importe_medio > 0 ? `Medio: ${formatCurrency(kpis.importe_medio)}` : undefined}
              />
              <StatCell
                label="Adjudicado"
                value={formatPercent(kpis.pct_adjudicado)}
                hint="De las licitaciones del órgano"
              />
              <StatCell
                label="Días hasta adjudicar (mediana)"
                value={kpis.lead_time_medio != null ? `${Math.round(kpis.lead_time_medio)} días` : EMPTY}
                hint="De la publicación a la adjudicación"
              />
              {kpis.top_adjudicatario && (
                <StatCell
                  className="col-span-2"
                  label="Primer adjudicatario"
                  value={kpis.top_adjudicatario}
                  hint={kpis.top_adj_importe > 0 ? formatCurrency(kpis.top_adj_importe) : undefined}
                />
              )}
            </StatStrip>

            {detalle.top_adjudicatarios?.length > 0 && (
              <section>
                <SectionTitle as="h3">Adjudicatarios principales</SectionTitle>
                <OrganosAdjudicatariosChart data={detalle.top_adjudicatarios} />
              </section>
            )}

            {detalle.estacionalidad?.length > 0 && (
              <section>
                <SectionTitle as="h3">Licitaciones por mes del año</SectionTitle>
                <OrganosEstacionalidadChart data={detalle.estacionalidad} />
              </section>
            )}

            {detalle.top_scored?.length > 0 && <OrganoTopScored items={detalle.top_scored} />}
          </div>
        ) : (
          <PanelEmpty
            title="Sin datos del órgano"
            hint="Este órgano no tiene licitaciones en el ámbito actual."
          />
        )}
      </div>
    </aside>
  );
}
