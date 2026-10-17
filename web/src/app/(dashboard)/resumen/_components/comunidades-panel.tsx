"use client";

import { useMemo, useState } from "react";
import { Panel, PanelEmpty, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { useFilters } from "@/lib/filters";
import { cn, formatCompactCurrency, formatNumber, formatPercent } from "@/lib/utils";
import type { AnalyticsOverview } from "@/lib/api-types";

/**
 * Reparto del ámbito por comunidad autónoma — `por_ccaa` de
 * `GET /analytics/overview`, la misma respuesta que la composición por estado.
 *
 * Es el otro corte del ámbito que sí filtra: la CCAA es una clave del ámbito,
 * y pulsar una fila la añade o la quita, como el estado en la composición
 * (clic en una marca filtra, no navega). El órgano no lo es, y por eso su
 * corte se retiró de aquí (ver `composicion-panel.tsx`).
 *
 * Una fila por comunidad, de más a menos expedientes, con su barra medida
 * contra la mayor y el porcentaje sobre los expedientes con comunidad escrito
 * al lado. Se ven las `VISIBLES` primeras —lo que mide la composición a su
 * lado—; el resto, a un clic. Cada fila lleva en texto lo que dice su barra.
 */

const ALTO = 56;

/** Filas a la vista antes de «Ver todas»: las de la composición de al lado. */
export const VISIBLES = 7;

function BarraComunidad({ n, maximo, atenuado }: { n: number; maximo: number; atenuado: boolean }) {
  const ancho = maximo > 0 ? Math.max(1.5, (n / maximo) * 100) : 0;
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 8"
      preserveAspectRatio="none"
      className="h-2 w-full overflow-hidden rounded-sm"
    >
      <rect width="100" height="8" className="fill-muted/60" />
      <rect width={ancho} height="8" className={cn("fill-primary", atenuado && "opacity-30")} />
    </svg>
  );
}

export function ComunidadesPanel({ className }: { className?: string }) {
  const { ccaas, setCcaas } = useFilters();
  const [todas, setTodas] = useState(false);

  const overview = useFilteredQuery<AnalyticsOverview>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    // Misma consulta y opciones que la tira de contexto y la composición: una
    // sola petición para los tres, y el fallo se pinta en el panel.
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
  );

  const filas = useMemo(() => overview.data?.por_ccaa ?? [], [overview.data?.por_ccaa]);
  const total = filas.reduce((suma, fila) => suma + fila.n, 0);
  const maximo = filas.reduce((mayor, fila) => Math.max(mayor, fila.n), 0);
  const visibles = todas ? filas : filas.slice(0, VISIBLES);

  const alternarCcaa = (ccaa: string) => {
    setCcaas(ccaas.includes(ccaa) ? ccaas.filter((valor) => valor !== ccaa) : [...ccaas, ccaa]);
  };

  return (
    <Panel className={cn("flex flex-col", className)}>
      <PanelTitle
        title="Por comunidad"
        hint={
          filas.length > 0
            ? `${formatNumber(filas.length)} comunidades · pulsa una para filtrar el ámbito`
            : "pulsa una comunidad para filtrar el ámbito"
        }
        actions={
          ccaas.length > 0 ? (
            <Button type="button" variant="ghost" size="sm" onClick={() => setCcaas([])}>
              Quitar filtro de comunidad
            </Button>
          ) : undefined
        }
      />

      {overview.error ? (
        <PanelError
          variant="inline"
          title="No se pudo cargar el reparto por comunidad"
          error={overview.error}
          onRetry={() => void overview.refetch()}
          height={ALTO}
        />
      ) : overview.isLoading ? (
        <PanelLoading height={ALTO} />
      ) : filas.length === 0 ? (
        <PanelEmpty
          title="Sin comunidad en el ámbito"
          hint="Ningún expediente del ámbito trae comunidad autónoma."
          height={ALTO}
        />
      ) : (
        <div className="flex flex-col gap-1">
          <div role="group" aria-label="Filtrar el ámbito por comunidad" className="flex flex-col gap-0.5">
            {visibles.map((fila) => {
              const activo = ccaas.includes(fila.ccaa);
              const atenuado = ccaas.length > 0 && !activo;
              return (
                <button
                  key={fila.ccaa}
                  type="button"
                  aria-pressed={activo}
                  onClick={() => alternarCcaa(fila.ccaa)}
                  className={cn(
                    "-mx-1.5 grid h-8 grid-cols-[minmax(0,6.5rem)_minmax(0,1fr)_3.5rem_2.75rem] items-center gap-2.5 rounded-md px-1.5 text-left text-tf-meta transition-colors active:duration-0 sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)_4.5rem_4.5rem_3.25rem]",
                    activo ? "bg-primary/10" : "hover:bg-primary/5 active:bg-primary/10",
                  )}
                >
                  <span className={cn("truncate", activo && "font-semibold")}>{fila.ccaa}</span>
                  <BarraComunidad n={fila.n} maximo={maximo} atenuado={atenuado} />
                  <span className="tf-tnum text-right font-semibold">{formatNumber(fila.n)}</span>
                  {/* El importe solo cabe desde `sm`: en un teléfono la barra
                      se quedaría sin sitio. */}
                  <span className="tf-tnum hidden text-right text-muted-foreground sm:inline">
                    {formatCompactCurrency(fila.importe)}
                  </span>
                  <span className="tf-tnum text-right text-muted-foreground">
                    {formatPercent((fila.n / total) * 100)}
                  </span>
                </button>
              );
            })}
          </div>
          {filas.length > VISIBLES && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="self-start"
              aria-expanded={todas}
              onClick={() => setTodas((valor) => !valor)}
            >
              {todas ? "Ver menos" : `Ver las ${formatNumber(filas.length)}`}
            </Button>
          )}
        </div>
      )}
    </Panel>
  );
}
