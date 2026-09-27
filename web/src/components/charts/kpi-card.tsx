"use client";

import * as React from "react";
import { TriangleAlert, type LucideIcon } from "lucide-react";
import { StatCell, StatStrip } from "@/components/console/panel";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { cn, EMPTY } from "@/lib/utils";

// A JS string constant (not raw JSX text) so it can't regress into literal
// `\uXXXX` escape sequences — JSX text/attribute strings are not run through
// the JS escape parser, unlike a real string literal referenced via `{}`.
const ANOMALY_LABEL = "Anomalía detectada (desviación >2σ)";

export interface KpiCardProps {
  title: string;
  value?: string;
  subtitle?: string;
  trend?: number;
  trendLabel?: string;
  /**
   * @deprecated Se ignora. Un KPI de consola no lleva icono en baldosa
   * tintada: era el bloque de dashboard por defecto de las plantillas.
   */
  icon?: LucideIcon;
  /** @deprecated Se ignora (no tenía llamadores). */
  sparkline?: React.ReactNode;
  /** Marca la cifra como anómala (desviación > 2σ): icono de aviso junto al rótulo. */
  anomaly?: boolean;
  /** @deprecated Se ignora (la franja de color no tenía llamadores). */
  accent?: "primary" | "hot" | "warm" | "cold" | "skip";
  /** @deprecated Se ignora (no tenía llamadores). */
  target?: string;
  /** Destino del detalle: la celda entera pasa a ser un enlace. */
  href?: string;
  loading?: boolean;
  className?: string;
  /** Color semántico de la cifra (un estado como «Online»/«Offline»). */
  tono?: "success" | "destructive" | "warning";
}

/**
 * KPI heredado: ahora es un adaptador que pinta `StatCell`, el KPI canónico de
 * la consola (rótulo a 11 px en frase, cifra a 20 px en sans, sin icono en
 * baldosa ni tarjeta con sombra). La API no cambia, así que sus llamadores
 * cambian de dibujo sin tocarse; `icon`, `accent`, `sparkline` y `target` se
 * aceptan y se ignoran.
 *
 * Suelto lleva su propio marco; dentro de una `StatStrip` (o `KpiStrip`) lo
 * pierde y la rejilla de 1 px hace de marco.
 *
 * Sin importadores desde el 2026-09-27 (eran 14): `no-restricted-imports` de
 * `eslint.config.mjs` impide volver a usarlo fuera de su test.
 *
 * @deprecated Usa `StatCell` dentro de `StatStrip` (`@/components/console/panel`).
 */
export const KpiCard = React.memo(function KpiCard({
  title,
  value,
  subtitle,
  trend,
  trendLabel,
  anomaly = false,
  href,
  loading = false,
  className,
  tono,
}: KpiCardProps) {
  return (
    <StatCell
      label={title}
      // Static render, no count-up: this is the number the user came to read,
      // and it re-triggers on every filter change.
      value={value ?? EMPTY}
      hint={trendLabel ?? subtitle}
      trend={trend}
      tono={tono}
      loading={loading}
      href={href}
      aria-label={href ? `${title}: ver detalle` : undefined}
      badge={anomaly ? <MarcaAnomalia /> : undefined}
      className={cn("h-full rounded-xl border border-border/60", className)}
    />
  );
});

/** Aviso de anomalía junto al rótulo: el icono en el color del aviso, sin fondo. */
function MarcaAnomalia() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex flex-none text-warning">
          <TriangleAlert className="h-3 w-3" aria-hidden="true" />
          <span className="sr-only">{ANOMALY_LABEL}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>{ANOMALY_LABEL}</TooltipContent>
    </Tooltip>
  );
}

/**
 * Tira de KPIs: ahora es `StatStrip`, con dos columnas por debajo de `lg` y
 * `columns` a partir de ahí.
 *
 * @deprecated Usa `StatStrip` de `@/components/console/panel`.
 */
export function KpiStrip({
  columns = 4,
  className,
  children,
}: {
  columns?: 2 | 3 | 4 | 5;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <StatStrip columns={columns} className={className}>
      {children}
    </StatStrip>
  );
}
