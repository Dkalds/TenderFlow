"use client";

import { cn } from "@/lib/utils";
import { estadoLabel } from "@/lib/estados";
import {
  CheckCircle2,
  Clock,
  XCircle,
  AlertTriangle,
  FileCheck,
  Timer,
  Flame,
  ThermometerSun,
  Snowflake,
  Ban,
  type LucideIcon,
} from "lucide-react";

/* ── Token-based variants ──────────────────────────────────────────── */

type Variant = "info" | "success" | "warning" | "destructive" | "neutral";

/* Static class strings so Tailwind's JIT can detect them. */
const VARIANT_CLASS: Record<Variant, string> = {
  info: "border-info/25 bg-info/12 text-info",
  success: "border-success/25 bg-success/12 text-success",
  warning: "border-warning/30 bg-warning/15 text-warning",
  destructive: "border-destructive/25 bg-destructive/12 text-destructive",
  neutral: "border-muted-foreground/20 bg-muted-foreground/10 text-muted-foreground",
};

/* ── Estado (tender state) ─────────────────────────────────────────── */

/**
 * Indexado por la etiqueta legible. El valor que llega de la API es el código
 * PLACSP (`PUB`, `EV`…), así que `estadoLabel` lo normaliza antes de buscar —
 * sin eso toda licitación real caía al badge neutro con el código en crudo
 * (ver `lib/estados.ts`).
 */
const ESTADO_STYLES: Record<string, { variant: Variant; icon: LucideIcon }> = {
  Publicada: { variant: "info", icon: Clock },
  "Evaluación": { variant: "info", icon: Timer },
  Adjudicada: { variant: "success", icon: CheckCircle2 },
  Resuelta: { variant: "success", icon: FileCheck },
  Desierta: { variant: "neutral", icon: AlertTriangle },
  Anulada: { variant: "destructive", icon: XCircle },
  "Anuncio previo": { variant: "neutral", icon: Clock },
  Creada: { variant: "neutral", icon: Clock },
  "En plazo": { variant: "info", icon: Timer },
  // Estados PSCP canonizados por la migración v91. Los dos primeros son
  // terminales (`shared/estados.py`), de ahí el icono de cerrado: un aviso
  // agregado recoge contratos ya celebrados y `En ejecución` ya está
  // adjudicado. `Consulta preliminar` sí es previa a la licitación.
  "Publicación agregada": { variant: "neutral", icon: FileCheck },
  "En ejecución": { variant: "success", icon: CheckCircle2 },
  "Consulta preliminar": { variant: "neutral", icon: Clock },
};

/* ── Band (scoring band) ───────────────────────────────────────────── */

const BAND_STYLES: Record<string, { variant: Variant; icon: LucideIcon }> = {
  Caliente: { variant: "destructive", icon: Flame },
  Atractiva: { variant: "warning", icon: ThermometerSun },
  Tibia: { variant: "info", icon: Snowflake },
  Descarte: { variant: "neutral", icon: Ban },
};

/* ── Component ─────────────────────────────────────────────────────── */

export type StatusKind = "estado" | "band";

export interface StatusBadgeProps {
  value: string | null | undefined;
  kind?: StatusKind;
  showIcon?: boolean;
  className?: string;
}

export function StatusBadge({
  value,
  kind = "estado",
  showIcon = false,
  className,
}: StatusBadgeProps) {
  if (!value) return <span className="text-muted-foreground">-</span>;

  const styles = kind === "estado" ? ESTADO_STYLES : BAND_STYLES;
  const text = kind === "estado" ? estadoLabel(value) : value;
  const entry = styles[text];
  const variant: Variant = entry?.variant ?? "neutral";
  const Icon = entry?.icon;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium",
        VARIANT_CLASS[variant],
        className,
      )}
      aria-label={`${kind === "estado" ? "Estado" : "Puntuación"}: ${text}`}
    >
      {showIcon && Icon ? (
        <Icon className="h-3 w-3" aria-hidden="true" />
      ) : (
        <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" aria-hidden="true" />
      )}
      {text}
    </span>
  );
}
