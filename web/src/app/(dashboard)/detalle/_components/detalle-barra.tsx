"use client";

import { ExportPopover } from "@/components/export-popover";
import { cn } from "@/lib/utils";

/**
 * Barra de la tabla: qué recortes están activos (y cómo quitarlos), la densidad
 * y la exportación.
 *
 * Los dos chips —ventana de cierre y orden— son la única pista de que la tabla
 * no está enseñando el catálogo entero: por eso llevan su propia «×» en vez de
 * esconderse en un menú.
 */
export function DetalleBarra({
  cierreLabel,
  onClearCierre,
  sortLabel,
  onClearSort,
  compact,
  onCompactChange,
}: {
  cierreLabel: string | null;
  onClearCierre: () => void;
  sortLabel: string | null;
  onClearSort: () => void;
  compact: boolean;
  onCompactChange: (compact: boolean) => void;
}) {
  return (
    <div className="flex h-11 flex-none items-center gap-2.5 border-b border-border/60 px-3.5">
      <span className="text-[12.5px] font-semibold">Detalle</span>
      <span className="hidden text-[11.5px] text-muted-foreground lg:inline">
        Tabla completa con todos los campos y exportación
      </span>
      <div className="flex-1" />
      {cierreLabel && (
        <button
          type="button"
          onClick={onClearCierre}
          title="Quitar el recorte por fecha de cierre"
          className="tf-pressable inline-flex h-6 items-center gap-1.5 rounded-md border border-primary/26 bg-primary/10 px-2 text-[11px] font-medium text-primary transition-colors duration-140 ease-out hover:bg-primary/20"
        >
          {cierreLabel}
          <span className="opacity-60">×</span>
        </button>
      )}
      {sortLabel && (
        <button
          type="button"
          onClick={onClearSort}
          className="tf-pressable inline-flex h-6 items-center gap-1.5 rounded-md border border-primary/26 bg-primary/10 px-2 text-[11px] font-medium text-primary transition-colors duration-140 ease-out hover:bg-primary/20"
        >
          {sortLabel}
          <span className="opacity-60">×</span>
        </button>
      )}
      <div className="flex items-center gap-0.5 rounded-md border border-border/70 p-0.5">
        {[
          { key: false, label: "Cómoda" },
          { key: true, label: "Compacta" },
        ].map((option) => (
          <button
            key={String(option.key)}
            type="button"
            onClick={() => onCompactChange(option.key)}
            aria-pressed={compact === option.key}
            className={cn(
              "h-[22px] rounded px-2 text-[11px] font-medium transition-colors duration-140 ease-out",
              compact === option.key
                ? "bg-primary/16 text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
      <ExportPopover className="[&>button]:h-7 [&>button]:px-2.5 [&>button]:py-0 [&>button]:text-xs" />
    </div>
  );
}
