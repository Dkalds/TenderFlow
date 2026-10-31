"use client";

import { ArrowDownUp, X } from "lucide-react";
import { Segmented } from "@/components/console/panel";
import { FiltroEtiquetaSelect } from "@/components/etiquetas/filtro-etiqueta";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ORDENES } from "./detalle-columnas";

/** Chip de un recorte activo, que se quita al pulsarlo. */
const CHIP_RECORTE =
  "tf-pressable inline-flex h-6 items-center gap-1.5 rounded-md border border-primary-line bg-primary-selected px-2 text-tf-micro font-medium text-primary hover:bg-primary-soft";

const DENSIDADES = [
  { value: "comoda", label: "Cómoda" },
  { value: "compacta", label: "Compacta" },
] as const;

/**
 * Barra de la tabla: qué recortes están activos (y cómo quitarlos), por qué
 * se ordena y la densidad.
 *
 * «Ordenar por» existe desde que la tabla agrupa seis datos en la celda
 * «Licitación» (2026-10): órgano, procedimiento, CCAA, CPV, expediente y
 * publicación ya no tienen cabecera que pulsar, y sin él no habría forma de
 * ordenar por ellos. Exportar vive en la barra del ámbito («Exportar ámbito»), con el
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
  orden,
  onOrdenar,
  compact,
  onCompactChange,
  etiqueta,
}: {
  cierreLabel: string | null;
  onClearCierre: () => void;
  sortLabel: string | null;
  onClearSort: () => void;
  orden: { id: string; desc: boolean } | null;
  onOrdenar: (orden: { id: string; desc: boolean } | null) => void;
  compact: boolean;
  onCompactChange: (compact: boolean) => void;
  /** F1.6 — filtro por etiqueta de favorito, sobre el listado entero (CU-28). */
  etiqueta?: { filtro: string; setFiltro: (filtro: string) => void };
}) {
  return (
    // `overflow-x-auto` y hijos `flex-none`: a 375 px, con los dos chips de
    // recorte puestos, la barra no cabe; antes empujaba el documento entero a
    // scroll horizontal y ahora se desplaza ella sola (móvil es consulta).
    <div className="flex h-11 flex-none items-center gap-2.5 overflow-x-auto border-b border-divider px-3.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden [&>*]:flex-none">
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
      <label className="flex items-center gap-1.5 text-tf-micro text-muted-foreground">
        Ordenar por
        <select
          value={orden?.id ?? ""}
          onChange={(event) =>
            onOrdenar(event.target.value ? { id: event.target.value, desc: orden?.desc ?? false } : null)
          }
          className="h-7 rounded-md border border-border bg-card px-1.5 text-tf-micro text-foreground"
        >
          <option value="">Sin orden</option>
          {ORDENES.map((opcion) => (
            <option key={opcion.key} value={opcion.key}>
              {opcion.label}
            </option>
          ))}
        </select>
      </label>
      {orden && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={() => onOrdenar({ ...orden, desc: !orden.desc })}
              aria-label={orden.desc ? "Ordenar de menor a mayor" : "Ordenar de mayor a menor"}
              className="tf-pressable grid h-7 w-7 place-items-center rounded-md border border-border bg-card text-muted-foreground hover:text-foreground"
            >
              <ArrowDownUp className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Invertir el orden</TooltipContent>
        </Tooltip>
      )}
      {etiqueta && (
        // Filtra en servidor: el listado, sus páginas y su total son los del
        // conjunto etiquetado entero, así que no hay «solo en esta página».
        <FiltroEtiquetaSelect value={etiqueta.filtro} onChange={etiqueta.setFiltro} />
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
