"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { TODAS_LAS_ETIQUETAS } from "@/components/etiquetas/filtro-etiqueta";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { TableroFiltros } from "./_components/tablero-filtros";
import TableroView from "./_components/tablero-view";

/**
 * Oportunidades — el espacio de ejecución, con las tres preguntas sobre las
 * oportunidades propias (reestructura 2026-09-20, «un espacio, una pregunta»):
 *
 * - **Tablero** (entrada): una columna por fase, mover con arrastre o menú. Es
 *   lo que era esta página entera; el cuerpo vive en
 *   `_components/tablero-view.tsx` y se importa estático porque es la vista de
 *   entrada y un `dynamic` le pondría un esqueleto delante en cada visita.
 * - **Cartera** (F4.3): contratos ganados en ejecución —fin efectivo,
 *   prórrogas, ventana de relicitación y «preparar renovación»—.
 * - **Rendimiento**: el embudo de `GET /pursuits/metrics` — win rate, valor
 *   ponderado, previsión por trimestre y pérdidas por motivo.
 *
 * Cartera y Rendimiento venían de Mi Pipeline (hoy Agenda); sus `?vista=`
 * viejos los reenvía aquella página. Se cargan bajo demanda, como en Mercado:
 * quien entra al tablero no paga las tablas de la cartera.
 *
 * Los filtros del tablero (búsqueda y etiqueta) son estado de esta página y no
 * del tablero porque sus controles van en la cabecera del espacio (`actions`),
 * que sólo se monta en esa vista. Dos `useState` sin efectos no cuestan nada
 * en las otras dos; lo que sí cuesta —las consultas— vive en `TableroView`,
 * que sólo se monta cuando el tablero es la vista activa.
 */

const loading = () => (
  <div className="space-y-4">
    <Skeleton className="h-24 w-full rounded-xl" />
    <Skeleton className="h-[320px] w-full rounded-xl" />
  </div>
);

const VIEWS: Record<string, React.ComponentType> = {
  cartera: dynamic(() => import("./_components/cartera-view"), { loading }),
  rendimiento: dynamic(() => import("./_components/rendimiento-view"), { loading }),
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "oportunidades")!;

export default function OportunidadesPage() {
  const { view, setView } = useSpaceView(SPACE);
  const [query, setQuery] = React.useState("");
  const [etiquetaFiltro, setEtiquetaFiltro] = React.useState<string>(TODAS_LAS_ETIQUETAS);

  // `useSpaceView` ya cae a la primera vista (`tablero`) ante un `?vista=`
  // desconocido; el `?? null` es sólo para que el tablero sea también el
  // destino de cualquier clave sin componente.
  const View = view === "tablero" ? null : (VIEWS[view] ?? null);
  const esTablero = View === null;

  return (
    <SpaceShell
      spaceKey="oportunidades"
      view={view}
      onViewChange={setView}
      actions={
        esTablero ? (
          <TableroFiltros
            query={query}
            onQuery={setQuery}
            etiqueta={etiquetaFiltro}
            onEtiqueta={setEtiquetaFiltro}
          />
        ) : undefined
      }
      // Sin relleno ni scroll propio sólo en el tablero: sus columnas hacen
      // su propio scroll. Cartera y Rendimiento son paneles normales.
      bleed={esTablero}
    >
      {View ? <View /> : <TableroView query={query} etiquetaFiltro={etiquetaFiltro} />}
    </SpaceShell>
  );
}
