"use client";

/**
 * Perfil del órgano abierto, en una franja horizontal bajo el mapa.
 *
 * Vivía en una columna de 420 px a la derecha, que sólo existía a partir de
 * `xl` y sólo tras un clic. Ahora ocupa el ancho entero, arranca abierto con
 * el primero del ranking y el mapa sigue ahí para saltar al siguiente.
 */

import Link from "next/link";
import { startTransition } from "react";
import { X } from "lucide-react";

import {
  EnlaceIr,
  PanelEmpty,
  PanelError,
  ROTULO_DATO,
  StatCell,
  StatStrip,
} from "@/components/console/panel";
import { SeguirBoton } from "@/components/seguir-boton";
import { Skeleton } from "@/components/ui/skeleton";
import { useCuentaDeOrgano } from "@/hooks/use-cuentas";
import { usePuedeEscribir } from "@/hooks/use-organization";
import { useScopedHref } from "@/lib/filters";
import { EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import type { OrganoDetailResponse } from "../_hooks/use-organos-view";
import { AdjudicatariosCuota, CuandoPublica, MejorPuntuadas } from "./organo-perfil-secciones";

/** Lo que ve un `viewer` en lugar de «Seguir»: de qué cuenta es el órgano. */
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

export function OrganoPerfil({
  organo,
  rango,
  ordenTxt,
  ccaa,
  detalle,
  isLoading,
  error,
  onRetry,
  onClose,
}: {
  organo: string;
  /** Posición del órgano en el ranking por la medida activa. */
  rango: number | null;
  ordenTxt: string;
  ccaa?: string;
  detalle: OrganoDetailResponse | undefined;
  isLoading: boolean;
  /** El fallo de la consulta del órgano: se dice, no se disfraza de «sin datos». */
  error?: unknown;
  onRetry?: () => void;
  onClose: () => void;
}) {
  const puedeEscribir = usePuedeEscribir();
  const scopedHref = useScopedHref();
  const kpis = detalle?.kpis;
  const eyebrow = [
    "Perfil del órgano",
    rango != null && rango > 0 ? `nº ${formatNumber(rango)} por ${ordenTxt}` : null,
    ccaa ?? null,
  ]
    .filter((pieza): pieza is string => pieza != null)
    .join(" · ");

  return (
    <section
      aria-label={`Perfil de ${organo}`}
      className="rounded-xl border border-primary/30 bg-card px-4 py-3.5"
    >
      <div className="grid gap-x-7 gap-y-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <p className={ROTULO_DATO}>{eyebrow}</p>
              <h2 className="mt-0.5 font-display text-tf-title font-semibold leading-tight">{organo}</h2>
            </div>
            {/* El control único «Seguir», que para un órgano crea o completa la
                cuenta objetivo de la organización activa (`/cuentas`). Un
                `viewer` no puede seguir: ve de qué cuenta es. */}
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
              aria-label="Cerrar perfil del órgano"
              onClick={() => startTransition(onClose)}
              className="tf-pressable grid h-6 w-6 flex-none place-items-center rounded-md border border-border/60 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          </div>

          {isLoading ? (
            <Skeleton className="h-36 w-full" />
          ) : kpis ? (
            <>
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
                  label="Días hasta adjudicar"
                  value={kpis.lead_time_medio != null ? `${Math.round(kpis.lead_time_medio)} días` : EMPTY}
                  hint="Mediana, de la publicación a la adjudicación"
                />
              </StatStrip>
              <div className="mt-auto flex flex-wrap gap-x-4 gap-y-1">
                <EnlaceIr href={scopedHref(`/detalle?q=${encodeURIComponent(organo)}`)}>
                  Ver sus {formatNumber(kpis.total_licitaciones)} licitaciones en Detalle
                </EnlaceIr>
              </div>
            </>
          ) : null}
        </div>

        {isLoading ? (
          <>
            <Skeleton className="h-44 w-full" />
            <Skeleton className="h-44 w-full" />
          </>
        ) : error ? (
          <div className="xl:col-span-2">
            <PanelError variant="inline" title="No se pudo cargar el órgano" error={error} onRetry={onRetry} />
          </div>
        ) : detalle && kpis ? (
          <>
            <AdjudicatariosCuota adjudicatarios={detalle.top_adjudicatarios ?? []} />
            <div className="flex min-w-0 flex-col gap-4">
              {detalle.estacionalidad?.length > 0 && <CuandoPublica estacionalidad={detalle.estacionalidad} />}
              {detalle.top_scored?.length > 0 && <MejorPuntuadas items={detalle.top_scored} />}
            </div>
          </>
        ) : (
          <div className="xl:col-span-2">
            <PanelEmpty
              size="sm"
              title="Sin datos del órgano"
              hint="Este órgano no tiene licitaciones en el ámbito actual."
            />
          </div>
        )}
      </div>
    </section>
  );
}
