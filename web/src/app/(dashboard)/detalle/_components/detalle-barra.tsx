"use client";

import { X } from "lucide-react";
import { Segmented } from "@/components/console/panel";
import { type FiltroEtiqueta, FiltroEtiquetaSelect } from "@/components/etiquetas/filtro-etiqueta";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/** Chip de un recorte activo, que se quita al pulsarlo. */
const CHIP_RECORTE =
  "tf-pressable inline-flex h-6 items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2 text-tf-micro font-medium text-primary hover:bg-primary/15";

const DENSIDADES = [
  { value: "comoda", label: "Cómoda" },
  { value: "compacta", label: "Compacta" },
] as const;

/**
 * Barra de la tabla: qué recortes están activos (y cómo quitarlos) y la
 * densidad. Exportar vive en la barra del ámbito («Exportar ámbito»), con el
 * mismo destino y los mismos filtros: aquí era un segundo botón para lo mismo.
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
      <span className="text-tf-body font-semibold">Detalle</span>
      <span className="hidden text-tf-meta text-muted-foreground lg:inline">
        Las licitaciones del ámbito, campo a campo
      </span>
      <div className="flex-1" />
      {/* La «×» es decorativa: lo que el lector anuncia es la etiqueta más
          «quitar». Antes el `title` nativo era la única pista de que el chip
          se pulsaba para quitarlo, y ni el teclado ni el táctil lo veían. */}
      {cierreLabel && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button type="button" onClick={onClearCierre} className={CHIP_RECORTE}>
              {cierreLabel}
              <X className="h-3 w-3" aria-hidden="true" />
              <span className="sr-only">(quitar)</span>
            </button>
          </TooltipTrigger>
          <TooltipContent>Quitar el recorte por fecha de cierre</TooltipContent>
        </Tooltip>
      )}
      {sortLabel && (
        <button type="button" onClick={onClearSort} className={CHIP_RECORTE}>
          {sortLabel}
          <X className="h-3 w-3" aria-hidden="true" />
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
        <span className="text-tf-micro text-muted-foreground">
          {etiqueta.cargando ? "Cargando etiquetas…" : "Sólo en esta página"}
        </span>
      )}
      <Segmented
        aria-label="Densidad de la tabla"
        size="xs"
        value={compact ? "compacta" : "comoda"}
        onChange={(densidad) => onCompactChange(densidad === "compacta")}
        options={DENSIDADES}
      />
    </div>
  );
}
