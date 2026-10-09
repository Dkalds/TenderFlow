"use client";

/**
 * El mapa de competidores: cada empresa es un punto, con su cuota como tamaño,
 * y dos lentes sobre el mismo plano.
 *
 * «Precio» cruza a qué baja gana cada una con el tamaño de sus contratos;
 * «Clientes», a cuántos órganos adjudica con cuánto depende del primero. Eran
 * dos dispersiones con las mismas burbujas en pestañas distintas; aquí es un
 * solo mapa y un conmutador. Las medianas de los puntos dibujados parten el
 * plano en cuatro perfiles.
 *
 * Un clic en un punto abre el perfil de la empresa. El mismo recorrido existe
 * con teclado en el ranking de debajo, que tiene un botón por empresa.
 */

import dynamic from "next/dynamic";

import { Panel, PanelEmpty, PanelLoading, PanelTitle, Segmented } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { ALTO_MAPA_COMPETIDORES } from "@/components/charts/competitors-charts";
import { CHART_SERIES } from "@/lib/chart-colors";
import { formatNumber } from "@/lib/utils";

import type { MapaModel } from "../_hooks/competidores-cruces";
import type { Lente } from "../_hooks/competidores-types";

const CompetidoresMapaChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetidoresMapaChart })),
  { ssr: false, loading: () => <PanelLoading height={ALTO_MAPA_COMPETIDORES} /> },
);

const OPCIONES_LENTE: { value: Lente; label: string }[] = [
  { value: "precio", label: "Precio" },
  { value: "clientes", label: "Clientes" },
];

const PISTA: Record<Lente, string> = {
  precio: "a qué baja gana cada empresa y de qué tamaño son sus contratos",
  clientes: "a cuántos órganos adjudica cada empresa y cuánto depende del primero",
};

/** Qué le falta a una empresa para dibujarse en cada lente. */
const SIN_DATO: Record<Lente, string> = {
  precio: "sin baja publicada o sin importe medio",
  clientes: "sin órgano identificado",
};

export function CompetidoresMapa({
  mapa,
  lente,
  onLenteChange,
  hayVigiladas,
  filtrado,
  isLoading,
  onEmpresaClick,
}: {
  mapa: MapaModel;
  lente: Lente;
  onLenteChange: (lente: Lente) => void;
  /** Vigilas alguna empresa: la leyenda explica el anillo. */
  hayVigiladas: boolean;
  /** Hay búsqueda local activa: el panel se marca como filtrado. */
  filtrado: boolean;
  isLoading: boolean;
  onEmpresaClick: (nombre: string) => void;
}) {
  const conMedianas = mapa.medianaX != null && mapa.medianaY != null;
  return (
    <Panel>
      <PanelTitle
        className="max-sm:flex-wrap"
        title="Mapa de competidores"
        hint={`${PISTA[lente]} · pulsa un punto para abrir su perfil`}
        actions={
          <>
            {filtrado && (
              <Badge variant="neutral" size="sm">
                Filtrado
              </Badge>
            )}
            <Segmented value={lente} onChange={onLenteChange} options={OPCIONES_LENTE} aria-label="Lente del mapa" size="xs" />
          </>
        }
      />
      {isLoading ? (
        <PanelLoading height={ALTO_MAPA_COMPETIDORES} />
      ) : mapa.puntos.length === 0 ? (
        <PanelEmpty
          title="Ninguna empresa que dibujar"
          hint={
            mapa.sinDato > 0
              ? `Lo que hay en la lista está ${SIN_DATO[lente]}. Prueba la otra lente.`
              : "Ningún competidor con adjudicaciones en el ámbito actual o con esa búsqueda."
          }
          height={ALTO_MAPA_COMPETIDORES}
        />
      ) : (
        <>
          <CompetidoresMapaChart
            puntos={mapa.puntos}
            lente={lente}
            medianaX={mapa.medianaX}
            medianaY={mapa.medianaY}
            onEmpresaClick={onEmpresaClick}
          />
          <ul className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-tf-micro text-muted-foreground">
            <li className="flex items-center gap-1.5">
              <svg aria-hidden="true" className="h-2.5 w-2.5 flex-none" viewBox="0 0 10 10">
                <circle cx="5" cy="5" r="5" fill={CHART_SERIES[0]} />
              </svg>
              Empresa · el tamaño es su cuota del importe
            </li>
            {hayVigiladas && (
              <li className="flex items-center gap-1.5">
                <svg aria-hidden="true" className="h-2.5 w-2.5 flex-none" viewBox="0 0 10 10">
                  <circle cx="5" cy="5" r="3.5" fill={CHART_SERIES[0]} stroke="hsl(var(--foreground))" strokeWidth="1.5" />
                </svg>
                La vigilas
              </li>
            )}
            <li className="flex items-center gap-1.5">
              <svg aria-hidden="true" className="h-2.5 w-2.5 flex-none" viewBox="0 0 10 10">
                <circle cx="5" cy="5" r="3" fill="hsl(var(--primary))" stroke="hsl(var(--primary))" strokeWidth="1.5" />
              </svg>
              Perfil abierto
            </li>
            {conMedianas && (
              <li className="flex items-center gap-1.5">
                <svg aria-hidden="true" className="h-2.5 w-4 flex-none" viewBox="0 0 16 10">
                  <line x1="0" y1="5" x2="16" y2="5" stroke="currentColor" strokeDasharray="3 2" />
                </svg>
                Medianas de las {formatNumber(mapa.puntos.length)} empresas del mapa
              </li>
            )}
            {mapa.sinDato > 0 && (
              <li>
                {formatNumber(mapa.sinDato)} {mapa.sinDato === 1 ? "empresa no se dibuja" : "empresas no se dibujan"}:{" "}
                {SIN_DATO[lente]}
              </li>
            )}
          </ul>
        </>
      )}
    </Panel>
  );
}
