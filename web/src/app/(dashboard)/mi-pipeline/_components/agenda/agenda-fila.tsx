"use client";

/**
 * Un compromiso de la agenda.
 *
 * La fila declara **qué clase de fecha** es la del chip (`metaLinea`): un «3 d»
 * suelto no distingue el plazo de presentación de una licitación, la tarea que
 * alguien se apuntó y la ventana en la que se espera la relicitación de un
 * contrato ya ganado. Tres relojes distintos, y hasta ahora los tres se pintaban
 * igual.
 *
 * **Por debajo de `md` deja de ser fila de tabla**: mirar la agenda en el móvil
 * es el otro caso de uso en movilidad, y una lista comprimida en cinco columnas
 * de 384 px obliga a scroll horizontal para llegar a la acción. Los envoltorios
 * se disuelven con `md:contents`, así que fila y ficha son el mismo árbol.
 */

import { cn, EMPTY, formatCompactCurrency } from "@/lib/utils";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import { AgendaAccion, type AccionesFila } from "./agenda-accion";
import {
  CHIP_POR_BANDA,
  claseDeIcono,
  etiquetaKind,
  GRID,
  ICONOS,
  metaLinea,
  plazoChip,
  tituloDe,
} from "./agenda-meta";

export function AgendaFila({
  item,
  activa,
  rowPad,
  onSeleccionar,
  acciones,
}: {
  item: PipelineAgendaItem;
  activa: boolean;
  rowPad: string;
  onSeleccionar: () => void;
  acciones: AccionesFila;
}) {
  const Icono = ICONOS[claseDeIcono(item)];

  return (
    <div
      data-active={activa || undefined}
      role="button"
      // Nombre explícito y no el texto que la fila contiene: sin él, el nombre
      // accesible de la fila era la concatenación de todo lo de dentro —chip,
      // importe y la etiqueta del botón de acción incluidos—, así que un lector
      // de pantalla anunciaba «… 940 mil € Preparar renovación» antes de que el
      // usuario supiera de qué contrato hablaba.
      aria-label={`${etiquetaKind(item)}: ${tituloDe(item)}. ${metaLinea(item)}`}
      tabIndex={0}
      onClick={onSeleccionar}
      onDoubleClick={acciones.onAbrir}
      onKeyDown={(event) => {
        if (event.key === "Enter") acciones.onAbrir();
      }}
      className={cn(
        "flex cursor-pointer flex-col gap-2 border-b border-border/40 px-3 py-3 transition-colors duration-120 ease-out",
        "md:grid md:items-center md:py-0",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45 focus-visible:ring-inset",
        GRID,
        rowPad,
        activa ? "bg-primary/8" : "hover:bg-secondary/60",
      )}
    >
      {/* Envoltorios de la ficha: `md:contents` los disuelve
          y sus hijos vuelven a las columnas de la tabla, en
          el mismo orden. Un árbol, dos presentaciones. */}
      <div className="flex min-w-0 items-center gap-2 md:contents">
        <span
          className={cn(
            "tf-tnum inline-flex h-5 flex-none items-center justify-center rounded-full px-1.5 font-mono text-[10.5px] font-semibold",
            CHIP_POR_BANDA[item.urgencia],
          )}
        >
          {plazoChip(item)}
        </span>
        <Icono className="h-3.5 w-3.5 flex-none text-muted-foreground" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          {/* Dos líneas en móvil, una en la tabla: el
              título de un expediente no cabe en 240 px. */}
          {/* El icono va `aria-hidden` porque la clase de compromiso ya está en
              el `aria-label` de la fila: repetirla la anunciaría dos veces. */}
          <p className="line-clamp-2 text-[12.5px] font-medium leading-[1.35] md:line-clamp-1">
            {tituloDe(item)}
          </p>
          <p className="truncate text-[10.5px] text-muted-foreground">{metaLinea(item)}</p>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-border/40 pt-2 md:contents">
        <span className="tf-tnum font-mono text-[11.5px] text-foreground/85 md:text-right">
          {item.importe_eur != null ? formatCompactCurrency(item.importe_eur) : EMPTY}
        </span>
        <span className="flex min-w-0 flex-none justify-end">
          <AgendaAccion item={item} acciones={acciones} />
        </span>
      </div>
    </div>
  );
}
