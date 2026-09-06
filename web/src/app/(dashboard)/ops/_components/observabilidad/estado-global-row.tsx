"use client";

/**
 * Semáforo de una línea con la hora del último chequeo.
 *
 * El punto de color nunca va solo: lleva su `aria-label` y el texto al lado
 * repite el estado, porque un círculo de 12 px es lo único que un lector de
 * pantalla no puede narrar.
 */

import { cn } from "@/lib/utils";
import { formatTime } from "@/lib/utils";
import type { EstadoGlobalSalud } from "../../_hooks/use-observabilidad";

const ETIQUETA: Record<EstadoGlobalSalud, string> = {
  ok: "Saludable",
  warn: "Verificando",
  error: "Error",
};

const TITULAR: Record<EstadoGlobalSalud, string> = {
  ok: "Sistema operativo",
  warn: "Verificando…",
  error: "Sistema con errores",
};

const COLOR: Record<EstadoGlobalSalud, string> = {
  ok: "bg-green-500",
  warn: "bg-yellow-500",
  error: "bg-red-500",
};

export function StatusDot({ status }: { status: EstadoGlobalSalud }) {
  return (
    <span
      className={cn("inline-block h-3 w-3 rounded-full", COLOR[status])}
      aria-label={`Estado: ${ETIQUETA[status]}`}
      title={ETIQUETA[status]}
    />
  );
}

export interface EstadoGlobalRowProps {
  estado: EstadoGlobalSalud;
  lastCheck: Date | null;
}

export function EstadoGlobalRow({ estado, lastCheck }: EstadoGlobalRowProps) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <StatusDot status={estado} />
      <span className="font-medium">{TITULAR[estado]}</span>
      {lastCheck && (
        <span className="text-muted-foreground">— Verificado {formatTime(lastCheck)}</span>
      )}
    </div>
  );
}
