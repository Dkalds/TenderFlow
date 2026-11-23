"use client";

import * as React from "react";
import { Aviso } from "@/components/console/panel";
import { cn } from "@/lib/utils";
import type { ScoringSignals } from "@/hooks/use-radar";

/**
 * Qué se le dice al usuario cuando el ranking avisa de que el score va cojo.
 *
 * No es decoración: una señal caída puntúa igual que una sin datos —todas las
 * filas neutrales en esa dimensión— y el ranking sigue pareciendo sano. La
 * señal de margen estuvo muerta semanas por ese motivo. El texto describe la
 * consecuencia para quien decide, no el fallo técnico.
 */
const SIGNAL_WARNINGS: Record<string, string> = {
  competencia: "sin histórico de competencia: esa dimensión puntúa neutra",
  margen: "sin predicción de baja: esa dimensión puntúa neutra",
  percentiles:
    "el importe se compara contra el histórico completo, no contra el mercado abierto",
  perfil: "no se pudo cargar tu perfil: el orden usa temporalmente los pesos globales",
  anulacion:
    "no se pudo leer la tasa de anulación por órgano: ningún expediente lleva esa penalización",
};

function signalWarnings(signals: ScoringSignals | null | undefined): string[] {
  if (!signals) return [];
  const avisos: string[] = [];
  if (signals.competencia !== "ok") avisos.push(SIGNAL_WARNINGS.competencia);
  if (signals.margen !== "ok") avisos.push(SIGNAL_WARNINGS.margen);
  if (signals.percentiles_fuente !== "universo_vivo") avisos.push(SIGNAL_WARNINGS.percentiles);
  if (signals.perfil !== "ok") avisos.push(SIGNAL_WARNINGS.perfil);
  // F1.4: `apagada` es una decisión del perfil, no una avería; solo `error` avisa.
  if (signals.anulacion_organo === "error") avisos.push(SIGNAL_WARNINGS.anulacion);
  return avisos;
}

/**
 * Banda de aviso bajo los controles, a todo el ancho (`Aviso` en su variante
 * `banda`): sin señales degradadas no se renderiza nada.
 */
export function RadarAvisoSenales({ signals }: { signals: ScoringSignals | null | undefined }) {
  const [entero, setEntero] = React.useState(false);
  const avisos = signalWarnings(signals);
  if (avisos.length === 0) return null;

  // En móvil la banda se queda en dos líneas hasta que se pide entera: a
  // 375 px medía cuatro, fijas encima de una lista que tiene su propio scroll.
  // El texto completo sigue en el DOM (el recorte es de CSS), así que el lector
  // de pantalla lo lee entero.
  return (
    <Aviso tone="warning" variant="banda" className="flex-none md:px-3.5">
      <span className={cn(!entero && "max-md:line-clamp-2")}>
        <span className="font-semibold">Score incompleto:</span> {avisos.join(" · ")}.
      </span>
      <button
        type="button"
        aria-expanded={entero}
        onClick={() => setEntero((valor) => !valor)}
        className="mt-0.5 block cursor-pointer font-medium text-primary md:hidden"
      >
        {entero ? "Ver menos" : "Ver entero"}
      </button>
    </Aviso>
  );
}
