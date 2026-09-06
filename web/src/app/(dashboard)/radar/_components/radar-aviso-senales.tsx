"use client";

import type { ScoringSignals } from "@/hooks/use-radar";

/**
 * Qué se le dice al usuario cuando el backend avisa de que el score va cojo.
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
};

export function signalWarnings(signals: ScoringSignals | null | undefined): string[] {
  if (!signals) return [];
  const avisos: string[] = [];
  if (signals.competencia !== "ok") avisos.push(SIGNAL_WARNINGS.competencia);
  if (signals.margen !== "ok") avisos.push(SIGNAL_WARNINGS.margen);
  if (signals.percentiles_fuente !== "universo_vivo") avisos.push(SIGNAL_WARNINGS.percentiles);
  if (signals.perfil !== "ok") avisos.push(SIGNAL_WARNINGS.perfil);
  return avisos;
}

/** Franja de aviso: sin señales degradadas no se renderiza nada. */
export function RadarAvisoSenales({ signals }: { signals: ScoringSignals | null | undefined }) {
  const avisos = signalWarnings(signals);
  if (avisos.length === 0) return null;

  return (
    <div
      role="status"
      className="flex-none border-b border-amber-500/25 bg-amber-500/8 px-3 py-1.5 text-[11.5px] leading-[1.45] text-amber-700 dark:text-amber-300 md:px-3.5"
    >
      <span className="font-medium">Score degradado</span> — {avisos.join(" · ")}.
    </div>
  );
}
