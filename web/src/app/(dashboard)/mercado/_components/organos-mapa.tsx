"use client";

/**
 * El mapa de compradores: cada órgano es un punto (licitaciones × importe,
 * tamaño = importe medio por licitación) y las medianas de los órganos
 * dibujados parten el plano en cuatro perfiles. Es lo que dos rankings
 * separados nunca enseñan: un órgano puede ser el tercero por licitaciones y el
 * primero por importe.
 *
 * Un clic en un punto abre el perfil del órgano. El mismo recorrido existe con
 * teclado en el ranking de debajo, que es una tabla con un botón por órgano.
 */

import dynamic from "next/dynamic";

import { Panel, PanelEmpty, PanelLoading, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { ALTO_MAPA } from "@/components/charts/organos-charts";
import { CHART_SERIES } from "@/lib/chart-colors";
import { formatCurrency, formatNumber } from "@/lib/utils";

import type { PuntoOrgano } from "../_hooks/use-organos-view";

const OrganosMapaChart = dynamic(
  () => import("@/components/charts/organos-charts").then((m) => ({ default: m.OrganosMapaChart })),
  { ssr: false, loading: () => <PanelLoading height={ALTO_MAPA} /> },
);

const VACIO = "Ningún órgano con licitaciones en el ámbito actual o con esa búsqueda.";

export function OrganosMapa({
  puntos,
  medianas,
  filtrado,
  isLoading,
  onOrganoClick,
}: {
  puntos: PuntoOrgano[];
  medianas: { count: number | null; importe: number | null };
  /** Hay búsqueda local activa: el panel se marca como filtrado. */
  filtrado: boolean;
  isLoading: boolean;
  onOrganoClick: (organo: string) => void;
}) {
  const conMedianas = medianas.count != null && medianas.importe != null;
  return (
    <Panel>
      <PanelTitle
        title="Mapa de compradores"
        hint="cuántas licitaciones publica cada órgano y cuánto importe suman · pulsa un punto para abrir su perfil"
        actions={
          filtrado ? (
            <Badge variant="neutral" size="sm">
              Filtrado
            </Badge>
          ) : null
        }
      />
      {isLoading ? (
        <PanelLoading height={ALTO_MAPA} />
      ) : puntos.length === 0 ? (
        <PanelEmpty title="Ningún órgano" hint={VACIO} height={ALTO_MAPA} />
      ) : (
        <>
          <OrganosMapaChart
            puntos={puntos}
            medianaCount={medianas.count}
            medianaImporte={medianas.importe}
            onOrganoClick={onOrganoClick}
          />
          <ul className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-tf-micro text-muted-foreground">
            <li className="flex items-center gap-1.5">
              <svg aria-hidden="true" className="h-2.5 w-2.5 flex-none" viewBox="0 0 10 10">
                <circle cx="5" cy="5" r="5" fill={CHART_SERIES[0]} />
              </svg>
              Órgano · el tamaño es su importe medio por licitación
            </li>
            <li className="flex items-center gap-1.5">
              <svg aria-hidden="true" className="h-2.5 w-2.5 flex-none" viewBox="0 0 10 10">
                <circle cx="5" cy="5" r="3" fill="hsl(var(--primary))" stroke="hsl(var(--primary))" strokeWidth="1.5" />
              </svg>
              Seleccionado
            </li>
            {conMedianas && (
              <li className="flex items-center gap-1.5">
                <svg aria-hidden="true" className="h-2.5 w-4 flex-none" viewBox="0 0 16 10">
                  <line x1="0" y1="5" x2="16" y2="5" stroke="currentColor" strokeDasharray="3 2" />
                </svg>
                Medianas de los {formatNumber(puntos.length)} órganos del mapa:{" "}
                <span className="tf-tnum">
                  {formatNumber(medianas.count)} licitaciones y {formatCurrency(medianas.importe)}
                </span>
              </li>
            )}
          </ul>
        </>
      )}
    </Panel>
  );
}
