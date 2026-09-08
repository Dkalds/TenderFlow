"use client";

/**
 * Semáforo de una línea con la hora del último chequeo.
 *
 * El punto de color nunca va solo: lleva su `aria-label` y el texto al lado
 * repite el estado, porque un círculo de 12 px es lo único que un lector de
 * pantalla no puede narrar.
 */

import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
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
    <Tooltip>
      <TooltipTrigger asChild>
        {/* `role="img"` porque el color es la única forma de leer el estado con
            la vista, y un `aria-label` sobre un `<span>` sin rol no lo exponen
            los lectores de pantalla de forma fiable. Sin `tabIndex`: una parada
            de tabulación que no hace nada al pulsarla es otra violación
            (`jsx-a11y/no-noninteractive-tabindex`), no una mejora. */}
        <span
          role="img"
          className={cn("inline-block h-3 w-3 rounded-full", COLOR[status])}
          aria-label={`Estado: ${ETIQUETA[status]}`}
        />
      </TooltipTrigger>
      <TooltipContent>{ETIQUETA[status]}</TooltipContent>
    </Tooltip>
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
