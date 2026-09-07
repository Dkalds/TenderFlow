"use client";

/**
 * Un compromiso de la agenda.
 *
 * **Por debajo de `md` deja de ser fila de tabla**: mirar la agenda en el móvil
 * es el otro caso de uso en movilidad, y una lista comprimida en cinco columnas
 * de 384 px obliga a scroll horizontal para llegar a «Seguir». Los envoltorios
 * se disuelven con `md:contents`, así que fila y ficha son el mismo árbol.
 */

import { X } from "lucide-react";
import { cn, EMPTY, formatCompactCurrency } from "@/lib/utils";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import { CHIP_POR_BANDA, GRID, KIND_META, metaLinea, plazoChip } from "./agenda-meta";

export function AgendaFila({
  item,
  activa,
  rowPad,
  onSeleccionar,
  onAbrir,
  onSeguir,
  onDescartar,
}: {
  item: PipelineAgendaItem;
  activa: boolean;
  rowPad: string;
  onSeleccionar: () => void;
  onAbrir: () => void;
  onSeguir: () => void;
  onDescartar: () => void;
}) {
  const Meta = KIND_META[item.kind];

  return (
    <div
      data-active={activa || undefined}
      role="button"
      tabIndex={0}
      onClick={onSeleccionar}
      onDoubleClick={onAbrir}
      onKeyDown={(event) => {
        if (event.key === "Enter") onAbrir();
      }}
      className={cn(
        "flex cursor-pointer flex-col gap-2 border-b border-border/40 px-3 py-3 transition-colors duration-120 ease-out",
        "md:grid md:items-center md:py-0",
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
        <Meta.icon
          className="h-3.5 w-3.5 flex-none text-muted-foreground"
          aria-label={Meta.label}
        />
        <div className="min-w-0 flex-1">
          {/* Dos líneas en móvil, una en la tabla: el
              título de un expediente no cabe en 240 px.
              Misma utilidad en las dos anchuras (`md:` y no
              `truncate`) para que el orden en cascada lo
              decida el prefijo, no la ordenación interna. */}
          <p className="line-clamp-2 text-[12.5px] font-medium leading-[1.35] md:line-clamp-1">
            {item.titulo ?? item.licitacion_id}
          </p>
          <p className="truncate text-[10.5px] text-muted-foreground">
            {metaLinea(item)}
          </p>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-border/40 pt-2 md:contents">
        <span className="tf-tnum font-mono text-[11.5px] text-foreground/85 md:text-right">
          {item.importe_eur != null ? formatCompactCurrency(item.importe_eur) : EMPTY}
        </span>
        {/* 32 px de alto en móvil frente a los 24 de la
            consola: 24×24 es el mínimo que exige WCAG 2.5.8,
            no una medida cómoda para el pulgar. */}
        <span className="flex flex-none justify-end">
          {item.kind === "pursuit" ? (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onAbrir();
              }}
              className="tf-pressable h-8 rounded-md border border-border/70 px-3 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground md:h-6 md:px-2"
            >
              Abrir
            </button>
          ) : (
            <span className="flex items-center gap-1.5 md:gap-1">
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onSeguir();
                }}
                className="tf-pressable h-8 rounded-md border border-primary/30 bg-primary/8 px-3 text-[11px] font-medium text-primary md:h-6 md:px-2"
              >
                {item.kind === "renovacion" ? "Anticipar" : "Seguir"}
              </button>
              {item.kind === "senal" && (
                <button
                  type="button"
                  aria-label="Descartar señal"
                  onClick={(event) => {
                    event.stopPropagation();
                    onDescartar();
                  }}
                  className="tf-pressable grid h-8 w-8 place-items-center rounded-md border border-border/70 text-muted-foreground transition-colors hover:text-destructive md:h-6 md:w-6"
                >
                  <X className="h-3.5 w-3.5 md:h-3 md:w-3" aria-hidden="true" />
                </button>
              )}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}
