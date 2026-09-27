"use client";

/** La tira de cabecera: si la API responde, cuándo y qué versión. */

import { StatCell, StatStrip } from "@/components/console/panel";
import { formatDate, formatTime } from "@/lib/utils";

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
    <StatStrip columns={3}>
      <StatCell
        label="Estado de la API"
        value={isOnline ? "En línea" : "Sin conexión"}
        hint={isOnline ? "Todos los servicios responden" : isError ? "Error de conexión" : undefined}
        tono={isLoading ? undefined : isOnline ? "success" : "destructive"}
        loading={isLoading}
      />
      <StatCell
        label="Último chequeo"
        value={lastCheck ? formatTime(lastCheck) : "—"}
        hint={lastCheck ? formatDate(lastCheck) : undefined}
        loading={isLoading}
      />
      <StatCell label="Versión de la API" value={version ?? "—"} loading={isLoading} />
    </StatStrip>
  );
}
