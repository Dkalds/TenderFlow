"use client";

import { cn } from "@/lib/utils";
import { estadoLabel } from "@/lib/estados";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { ChipBanda } from "@/components/console/chip-banda";
import {
  CircleCheck,
  CircleX,
  Clock,
  FileCheck,
  Timer,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

/* ── Tonos ─────────────────────────────────────────────────────────── */

type Variant = "info" | "success" | "warning" | "destructive" | "neutral";

/** El tono de la chapa es una variante de `Badge`: un solo dibujo de chip. */
const VARIANTE_BADGE: Record<Variant, NonNullable<BadgeProps["variant"]>> = {
  info: "info",
  success: "success",
  warning: "warning",
  destructive: "destructive",
  neutral: "neutral",
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
  Adjudicada: { variant: "success", icon: CircleCheck },
  Resuelta: { variant: "success", icon: FileCheck },
  Desierta: { variant: "neutral", icon: TriangleAlert },
  Anulada: { variant: "destructive", icon: CircleX },
  "Anuncio previo": { variant: "neutral", icon: Clock },
  Creada: { variant: "neutral", icon: Clock },
  "En plazo": { variant: "info", icon: Timer },
  // Estados PSCP canonizados por la migración v91. Los dos primeros son
  // terminales (`shared/estados.py`), de ahí el icono de cerrado: un aviso
  // agregado recoge contratos ya celebrados y `En ejecución` ya está
  // adjudicado. `Consulta preliminar` sí es previa a la licitación.
  "Publicación agregada": { variant: "neutral", icon: FileCheck },
  "En ejecución": { variant: "success", icon: CircleCheck },
  "Consulta preliminar": { variant: "neutral", icon: Clock },
};

/* ── Component ─────────────────────────────────────────────────────── */

export type StatusKind = "estado" | "band";

export interface StatusBadgeProps {
  value: string | null | undefined;
  kind?: StatusKind;
  /** Solo para `kind="estado"`: icono del estado en vez del punto. */
  showIcon?: boolean;
  className?: string;
}

/**
 * Chapa de estado de una licitación, o de su banda de puntuación.
 *
 * - `kind="estado"`: un `Badge` del tono del estado con un punto (o su icono,
 *   con `showIcon`).
 * - `kind="band"`: delega en `ChipBanda` (`@/components/console/panel`), el
 *   chip único de banda sobre los tokens `--score-*`. Sin iconos del tiempo ni
 *   la variante de error para «Caliente»: una banda alta no es un fallo.
 */
export function StatusBadge({
  value,
  kind = "estado",
  showIcon = false,
  className,
}: StatusBadgeProps) {
  if (!value) return <span className="text-muted-foreground">-</span>;

  if (kind === "band") {
    return <ChipBanda banda={value} className={className} aria-label={`Puntuación: ${value}`} />;
  }

  const text = estadoLabel(value);
  const entry = ESTADO_STYLES[text];
  const variant: Variant = entry?.variant ?? "neutral";
  const Icon = entry?.icon;

  return (
    <Badge
      variant={VARIANTE_BADGE[variant]}
      className={cn("gap-1.5", className)}
      aria-label={`Estado: ${text}`}
    >
      {showIcon && Icon ? (
        <Icon aria-hidden="true" />
      ) : (
        <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" aria-hidden="true" />
      )}
      {text}
    </Badge>
  );
}
