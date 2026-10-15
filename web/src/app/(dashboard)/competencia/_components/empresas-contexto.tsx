"use client";

import { UMBRAL_IMPORTE_RESUELTO, importeResueltoBajoUmbral, useEmpresasStats } from "@/hooks/use-empresas-stats";
import { useEmpresasWatchlist } from "@/hooks/use-empresas-watchlist";
import { formatNumber, formatPercent } from "@/lib/utils";
import { ContextLine } from "./context-line";

/**
 * La línea de contexto de Competencia › Empresas y › Revisión: cuántas
 * canónicas hay, cuánto importe está resuelto, cuántas se vigilan y cuántas
 * coincidencias esperan en la cola.
 *
 * Va en la cabecera del espacio (`actions` de `SpaceShell`) solo en esas dos
 * vistas: es el estado del maestro, y en Competidores o en UTEs no es lo que se
 * está mirando. Los dos datos que llevan a la cola abren su pestaña.
 */
export function EmpresasContexto({ onAbrirCola }: { onAbrirCola: () => void }) {
  const stats = useEmpresasStats();
  // Solo para el recuento de «Vigiladas». Vigilar y dejar de vigilar lo hace
  // `SeguirBoton` (ADR-031 §C) en la fila y en la ficha, sobre esta misma
  // consulta, así que el recuento se mueve con el botón. La lista, con la
  // actividad de cada una, está en la vista Competidores.
  const { watchedIds } = useEmpresasWatchlist();

  const pctImporte = stats.data?.pct_importe;
  const contexto = [
    {
      key: "canonicas",
      label: "Canónicas",
      value: stats.data ? formatNumber(stats.data.empresas, "es-ES", { agruparSiempre: true }) : "…",
      title: "Empresas en el maestro",
    },
    {
      key: "resuelto",
      label: "Importe resuelto",
      value: pctImporte != null ? formatPercent(pctImporte) : "…",
      warn: importeResueltoBajoUmbral(stats.data),
      title: stats.data
        ? `${formatNumber(stats.data.adjudicaciones_enlazadas, "es-ES", { agruparSiempre: true })} de ${formatNumber(stats.data.adjudicaciones_total, "es-ES", { agruparSiempre: true })} adjudicaciones enlazadas. Por debajo del ${UMBRAL_IMPORTE_RESUELTO}% las cuotas de Competencia arrastran el error. Abre la cola de revisión`
        : "Cobertura de la resolución de entidades",
      onClick: onAbrirCola,
    },
    {
      key: "vigiladas",
      label: "Vigiladas",
      value: formatNumber(watchedIds.size),
      title: "Empresas con alerta diaria · abre la lista en Competidores",
      href: "/competencia?vista=competidores",
    },
    {
      key: "revisiones",
      label: "Revisiones",
      value: stats.data ? formatNumber(stats.data.revisiones_pendientes) : "…",
      title: "Coincidencias dudosas pendientes · abre la cola",
      onClick: onAbrirCola,
    },
  ];

  return <ContextLine items={contexto} />;
}
