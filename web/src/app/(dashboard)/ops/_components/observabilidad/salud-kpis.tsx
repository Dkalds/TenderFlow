"use client";

/** Las tres tarjetas de cabecera: si la API responde, cuándo y qué versión. */

import { Activity, Server } from "lucide-react";
import { KpiCard } from "@/components/charts/kpi-card";
import { cn, formatDate, formatTime } from "@/lib/utils";

export interface SaludKpisProps {
  isLoading: boolean;
  isError: boolean;
  isOnline: boolean;
  /** Momento del último health que llegó; `null` mientras no haya ninguno. */
  lastCheck: Date | null;
  version: string | undefined;
}

export function SaludKpis({ isLoading, isError, isOnline, lastCheck, version }: SaludKpisProps) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <KpiCard
        title="Estado API"
        value={isLoading ? undefined : isOnline ? "Online" : "Offline"}
        subtitle={
          isOnline
            ? "Todos los servicios operativos"
            : isError
              ? "Error de conexión"
              : undefined
        }
        icon={Activity}
        loading={isLoading}
        className={cn(
          !isLoading && isOnline && "border-green-200 dark:border-green-800",
          !isLoading && !isOnline && "border-red-200 dark:border-red-800",
        )}
      />
      <KpiCard
        title="Último health check"
        value={lastCheck ? formatTime(lastCheck) : undefined}
        subtitle={lastCheck ? formatDate(lastCheck) : undefined}
        icon={Server}
        loading={isLoading}
      />
      <KpiCard
        title="Versión API"
        value={isLoading ? undefined : version ?? "N/A"}
        icon={Server}
        loading={isLoading}
      />
    </div>
  );
}
