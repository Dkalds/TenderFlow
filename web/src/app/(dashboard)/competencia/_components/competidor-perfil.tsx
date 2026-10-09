"use client";

/**
 * Perfil del competidor abierto, en una franja bajo el mapa.
 *
 * Vivía en una columna de 420 px a la derecha, que solo existía a partir de
 * `xl` y solo tras un clic, y «Contra mí» estaba en su segunda pestaña. Ahora
 * ocupa el ancho entero a cualquier tamaño, arranca abierto con la primera del
 * ranking y lo que el equipo más quiere saber —cómo le ha ido contra esa
 * empresa— está a la vista.
 *
 * Mientras llega el perfil, las cifras de cabecera son las de la fila del
 * ranking, que ya están descargadas: la franja no salta al cambiar de empresa.
 */

import { startTransition } from "react";
import { X } from "lucide-react";

import {
  EnlaceIr,
  PanelError,
  ROTULO_DATO,
  SectionTitle,
  StatCell,
  StatStrip,
} from "@/components/console/panel";
import {
  buildExecutiveSummary,
  variacionFrenteAnterior,
  type CompanyProfileData,
} from "@/components/competitors/company-profile-types";
import { CompanyYearTrend } from "@/components/competitors/company-year-trend";
import { SeguirBoton } from "@/components/seguir-boton";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { valorOEmpty } from "@/lib/cobertura";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import type { Competitor } from "../_hooks/competidores-types";
import { ContraTi, DondeGana, QuienLeCompra } from "./competidor-perfil-secciones";

export function CompetidorPerfil({
  empresa,
  rango,
  ordenTxt,
  totalEmpresas,
  empresaId,
  empresaIds,
  perfil,
  isLoading,
  error,
  onRetry,
  enDuelo,
  onClose,
}: {
  empresa: Competitor;
  /** Posición en el ranking por la medida activa. */
  rango: number | null;
  ordenTxt: string;
  totalEmpresas: number | null;
  /** Identidad principal del grupo; `undefined` = sin identidad en el maestro. */
  empresaId: number | undefined;
  empresaIds: number[];
  perfil: CompanyProfileData | undefined;
  isLoading: boolean;
  /** El fallo de la consulta del perfil: se dice, no se disfraza de «sin datos». */
  error?: unknown;
  onRetry?: () => void;
  /** Está en el cara a cara de debajo. */
  enDuelo: boolean;
  onClose: () => void;
}) {
  const totales = perfil?.totales;
  const comparacion = perfil?.comparacion;
  const posicion = perfil?.posicion_mercado;
  const rotulo = [
    "Perfil del competidor",
    rango != null && rango > 0
      ? `n.º ${formatNumber(rango)}${totalEmpresas ? ` de ${formatNumber(totalEmpresas)}` : ""} por ${ordenTxt}`
      : null,
  ]
    .filter((pieza): pieza is string => pieza != null)
    .join(" · ");
  const hrefAnalisis =
    empresaId == null
      ? null
      : empresaIds.length > 1
        ? `/competencia/empresa/${empresaId}?ids=${empresaIds.join(",")}`
        : `/competencia/empresa/${empresaId}`;

  return (
    <section
      aria-label={`Perfil de ${empresa.nombre}`}
      className="rounded-xl border border-primary/30 bg-card px-4 py-3.5"
    >
      <div className="grid grid-cols-1 gap-x-7 gap-y-5 md:grid-cols-2 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,0.85fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <p className={ROTULO_DATO}>{rotulo}</p>
              <h2 className="mt-0.5 font-display text-tf-title font-semibold leading-tight">{empresa.nombre}</h2>
              {(empresa.es_agrupacion || perfil?.empresa.es_ute || enDuelo) && (
                <p className="mt-1 flex flex-wrap gap-1.5">
                  {empresa.es_agrupacion && (
                    <Badge variant="secondary" size="sm">
                      Suma {formatNumber(empresaIds.length)} identidades
                    </Badge>
                  )}
                  {perfil?.empresa.es_ute && (
                    <Badge variant="info" size="sm">
                      UTE
                    </Badge>
                  )}
                  {enDuelo && (
                    <Badge variant="default" size="sm">
                      En el cara a cara
                    </Badge>
                  )}
                </p>
              )}
            </div>
            <button
              type="button"
              aria-label="Cerrar perfil del competidor"
              onClick={() => startTransition(onClose)}
              className="tf-pressable grid h-6 w-6 flex-none place-items-center rounded-md border border-border/60 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          </div>

          <StatStrip columns={2}>
            <StatCell
              label="Importe adjudicado"
              value={formatCurrency(totales?.importe_total ?? empresa.importe)}
              hint={variacionFrenteAnterior(comparacion?.variacion_importe_pct, "En el ámbito actual")}
            />
            <StatCell
              label="Adjudicaciones"
              value={formatNumber(totales?.contratos ?? empresa.count)}
              hint={variacionFrenteAnterior(comparacion?.variacion_contratos_pct, "Expedientes ganados")}
            />
            <StatCell
              label="Cuota y posición"
              // La cuota y el puesto salen del mismo sitio —el perfil— para
              // que no se lean juntas dos cifras de universos distintos.
              value={`${formatPercent(posicion?.cuota_pct ?? empresa.cuota)}${posicion?.rank ? ` · n.º ${formatNumber(posicion.rank)}` : ""}`}
              hint={posicion ? `Entre ${formatNumber(posicion.empresas)} empresas` : "Cuota del importe del ámbito"}
            />
            <StatCell
              label="Baja media"
              value={valorOEmpty(totales ? totales.baja_media_pct : empresa.baja_media, formatPercent)}
              hint="Cuánto por debajo del presupuesto"
            />
          </StatStrip>

          {perfil && <p className="text-tf-meta text-muted-foreground">{buildExecutiveSummary(perfil)}</p>}

          <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-2">
            {empresaId != null && (
              // El control único de ADR-031 §C. Sigue el grupo entero de
              // identidades equivalentes: vigilar una empresa deduplicada es
              // vigilar todos sus `empresa_id`.
              <SeguirBoton
                targetType="empresa"
                targetId={String(empresaId)}
                equivalentes={empresaIds.map(String)}
                icono="ojo"
                nombreAccesible="visible"
                textos={{ seguir: "Vigilar empresa", siguiendo: "Vigilando" }}
                clases={{
                  base: "",
                  activo: buttonVariants({ variant: "secondary", size: "sm" }),
                  inactivo: buttonVariants({ variant: "outline", size: "sm" }),
                }}
              />
            )}
            {hrefAnalisis ? (
              <EnlaceIr href={hrefAnalisis}>Ver análisis y listado completo</EnlaceIr>
            ) : (
              <EnlaceIr href={`/empresas?q=${encodeURIComponent(empresa.nombre)}`}>Buscarla en Empresas</EnlaceIr>
            )}
          </div>
        </div>

        {empresaId == null ? (
          <div className="md:col-span-1 xl:col-span-3">
            <SectionTitle as="h3">Sin identidad en el maestro de empresas</SectionTitle>
            <p className="max-w-prose text-tf-meta text-muted-foreground">
              Esta adjudicataria todavía no está resuelta a una empresa del maestro, así que no hay perfil que cruzar:
              dónde gana, quién le compra y cómo le ha ido contra ti aparecen cuando lo esté.
            </p>
          </div>
        ) : isLoading ? (
          <>
            <Skeleton className="h-48 w-full" />
            <Skeleton className="h-48 w-full" />
            <Skeleton className="h-48 w-full" />
          </>
        ) : error || !perfil ? (
          <div className="md:col-span-1 xl:col-span-3">
            <PanelError variant="inline" title="No se pudo cargar el perfil" error={error} onRetry={onRetry} />
          </div>
        ) : (
          <>
            <DondeGana porCcaa={perfil.por_ccaa} territorios={perfil.totales.territorios} />
            <QuienLeCompra organos={perfil.organos_principales} totalOrganos={perfil.totales.organos} />
            <div className="flex min-w-0 flex-col gap-4">
              <section>
                <SectionTitle as="h3" hint="importe y adjudicaciones por año">
                  Progreso anual
                </SectionTitle>
                <CompanyYearTrend rows={perfil.por_anio} compact />
              </section>
              <ContraTi empresaId={empresaId} empresaIds={empresaIds} hrefDetalle={hrefAnalisis ?? "/competencia"} />
            </div>
          </>
        )}
      </div>
    </section>
  );
}
