"use client";

/**
 * El selector de periodo de Rendimiento.
 *
 * Tres botones con `aria-pressed` dentro de un `role="group"` con nombre, y no
 * un `tablist`: no conmutan entre paneles, acotan la ventana de la que hablan
 * todos. La elección vive en `?periodo=` —la escribe el llamante— para que una
 * ventana concreta se pueda compartir y recargar.
 */
import { cn } from "@/lib/utils";
import { PERIODOS, type PeriodoClave } from "../../_lib/periodo";

export function PeriodoSelector({
  periodo,
  onChange,
}: {
  periodo: PeriodoClave;
  onChange: (periodo: PeriodoClave) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Periodo de las métricas"
      className="flex items-center gap-0.5 rounded-md border border-border/60 p-0.5"
    >
      {PERIODOS.map((opcion) => {
        const activo = opcion.clave === periodo;
        return (
          <button
            key={opcion.clave}
            type="button"
            aria-pressed={activo}
            onClick={() => onChange(opcion.clave)}
            className={cn(
              "tf-pressable h-6 rounded px-2 text-[11px] font-medium transition-colors duration-110",
              activo ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {opcion.label}
          </button>
        );
      })}
    </div>
  );
}
