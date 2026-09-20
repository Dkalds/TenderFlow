"use client";

import { ExportPopover } from "@/components/export-popover";
import { type FiltroEtiqueta, FiltroEtiquetaSelect } from "@/components/etiquetas/filtro-etiqueta";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
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
  etiqueta,
}: {
  cierreLabel: string | null;
  onClearCierre: () => void;
  sortLabel: string | null;
  onClearSort: () => void;
  compact: boolean;
  onCompactChange: (compact: boolean) => void;
  /** F1.6 — filtro por etiqueta de favorito sobre la página cargada. */
  etiqueta?: FiltroEtiqueta;
}) {
  return (
    // `overflow-x-auto` y hijos `flex-none`: a 375 px, con los dos chips de
    // recorte puestos, la barra no cabe; antes empujaba el documento entero a
    // scroll horizontal y ahora se desplaza ella sola (móvil es consulta).
    <div className="flex h-11 flex-none items-center gap-2.5 overflow-x-auto border-b border-border/60 px-3.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden [&>*]:flex-none">
      <span className="text-[12.5px] font-semibold">Detalle</span>
      <span className="hidden text-[11.5px] text-muted-foreground lg:inline">
        Tabla completa con todos los campos y exportación
      </span>
      <div className="flex-1" />
      {/* La «×» es decorativa: lo que el lector anuncia es la etiqueta más
          «quitar». Antes el `title` nativo era la única pista de que el chip
          se pulsaba para quitarlo, y ni el teclado ni el táctil lo veían. */}
      {cierreLabel && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={onClearCierre}
              className="tf-pressable inline-flex h-6 items-center gap-1.5 rounded-md border border-primary/26 bg-primary/10 px-2 text-[11px] font-medium text-primary transition-colors duration-140 ease-out hover:bg-primary/20"
            >
              {cierreLabel}
              <span aria-hidden="true">×</span>
              <span className="sr-only">(quitar)</span>
            </button>
          </TooltipTrigger>
          <TooltipContent>Quitar el recorte por fecha de cierre</TooltipContent>
        </Tooltip>
      )}
      {sortLabel && (
        <button
          type="button"
          onClick={onClearSort}
          className="tf-pressable inline-flex h-6 items-center gap-1.5 rounded-md border border-primary/26 bg-primary/10 px-2 text-[11px] font-medium text-primary transition-colors duration-140 ease-out hover:bg-primary/20"
        >
          {sortLabel}
          <span aria-hidden="true">×</span>
          <span className="sr-only">(quitar)</span>
        </button>
      )}
      {etiqueta && (
        // Sin parámetro de etiqueta en `/licitaciones`: filtra las filas de
        // esta página, y el nombre accesible lo dice.
        <FiltroEtiquetaSelect
          value={etiqueta.filtro}
          onChange={etiqueta.setFiltro}
          alcance="en esta página"
        />
      )}
      {etiqueta?.activo && (
        <span className="text-[11px] text-muted-foreground">
          {etiqueta.cargando ? "Cargando etiquetas…" : "Sólo en esta página"}
        </span>
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
