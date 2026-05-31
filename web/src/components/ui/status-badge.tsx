"use client";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
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

/* ── Estado (tender state) ─────────────────────────────────────────── */

const ESTADO_STYLES: Record<string, { className: string; icon: LucideIcon }> = {
  Publicada: {
    className: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300",
    icon: Clock,
  },
  Adjudicada: {
    className: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300",
    icon: CheckCircle2,
  },
  Resuelta: {
    className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-300",
    icon: FileCheck,
  },
  Desierta: {
    className: "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-300",
    icon: AlertTriangle,
  },
  Anulada: {
    className: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300",
    icon: XCircle,
  },
  "En plazo": {
    className: "bg-sky-100 text-sky-800 dark:bg-sky-900 dark:text-sky-300",
    icon: Timer,
  },
};

/* ── Band (scoring band) ───────────────────────────────────────────── */

const BAND_STYLES: Record<string, { className: string; icon: LucideIcon }> = {
  Caliente: {
    className: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300",
    icon: Flame,
  },
  Atractiva: {
    className: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300",
    icon: ThermometerSun,
  },
  Tibia: {
    className: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300",
    icon: Snowflake,
  },
  Descarte: {
    className: "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-300",
    icon: Ban,
  },
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
  const entry = styles[value];
  const Icon = entry?.icon;

  return (
    <Badge
      variant="secondary"
      className={cn("text-xs gap-1", entry?.className, className)}
      aria-label={`${kind === "estado" ? "Estado" : "Puntuación"}: ${value}`}
    >
      {showIcon && Icon && <Icon className="h-3 w-3" aria-hidden="true" />}
      {value}
    </Badge>
  );
}
