"use client";

import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Pista } from "@/components/ui/pista";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { SHORTCUTS } from "./detalle-columnas";

const EXPLICACION_ORDEN_LOCAL =
  "Solo título, importe y fecha se ordenan sobre todas las licitaciones; esta columna ordena las filas de la página que ves.";

const BOTON_PAGINA =
  "tf-pressable grid h-6.5 w-6.5 place-items-center rounded-md border border-border/70 text-tf-meta text-muted-foreground hover:text-foreground disabled:cursor-default disabled:opacity-35";

/**
 * Pie: qué tramo se está viendo, los atajos y la paginación completa.
 *
 * El aviso «orden sobre esta página» no es cosmético: cuando la columna activa
 * no la sabe ordenar el backend, lo que se ve ordenado son las 25 filas
 * cargadas y no el total. Sin ese chip la tabla prometería un orden global que
 * no tiene.
 */
export function DetallePie({
  showingLine,
  clientSorted,
  pageIndex,
  totalPages,
  pageWindow,
  canPrevious,
  canNext,
  canLast,
  onPageChange,
}: {
  showingLine: string;
  clientSorted: boolean;
  pageIndex: number;
  totalPages: number;
  pageWindow: number[];
  canPrevious: boolean;
  canNext: boolean;
  /**
   * «Última página». Con paginación por cursor sólo se llega a una página ya
   * alcanzada, así que no basta con `canNext`: por defecto, el mismo valor.
   */
  canLast?: boolean;
  onPageChange: (page: number) => void;
}) {
  return (
    // Mismo criterio que la barra de arriba: con cinco páginas en la ventana
    // la paginación no cabe a 375 px y se desplaza el pie, no el documento.
    <div className="flex h-11 flex-none items-center gap-3 overflow-x-auto border-t border-border/70 bg-card px-3.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <span className="tf-tnum text-tf-micro text-muted-foreground">{showingLine}</span>
      {/* La explicación va también en `sr-only`: con el `title` de antes solo
          la veía quien pasaba el ratón, y es justo la advertencia que dice que
          el orden no cubre el catálogo entero. */}
      {clientSorted && (
        <Pista contenido={EXPLICACION_ORDEN_LOCAL}>
          <Badge variant="warning" size="sm">
            Orden sobre esta página
            <span className="sr-only">. {EXPLICACION_ORDEN_LOCAL}</span>
          </Badge>
        </Pista>
      )}
      <div className="flex-1" />
      {SHORTCUTS.map((shortcut) => (
        <span
          key={shortcut.key}
          className="hidden items-center gap-1.5 text-tf-micro text-muted-foreground xl:inline-flex"
        >
          <kbd className="rounded-sm border border-border/70 px-1 py-0.5 font-mono text-tf-micro font-medium">
            {shortcut.key}
          </kbd>
          {shortcut.label}
        </span>
      ))}
      <span className="mx-0.5 hidden h-4.5 w-px bg-border/70 xl:block" aria-hidden="true" />
      <nav aria-label="Paginación" className="flex items-center gap-0.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label="Primera página"
              className={BOTON_PAGINA}
              onClick={() => onPageChange(0)}
              disabled={!canPrevious}
            >
              <ChevronsLeft className="h-3 w-3" aria-hidden="true" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Primera página</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label="Página anterior"
              className={BOTON_PAGINA}
              onClick={() => onPageChange(pageIndex - 1)}
              disabled={!canPrevious}
            >
              <ChevronLeft className="h-3 w-3" aria-hidden="true" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Anterior</TooltipContent>
        </Tooltip>
        {pageWindow.map((page) => (
          <button
            key={page}
            type="button"
            aria-current={page === pageIndex ? "page" : undefined}
            onClick={() => onPageChange(page)}
            className={cn(
              "tf-tnum tf-pressable h-6.5 min-w-6.5 rounded-md border px-1 text-tf-micro",
              page === pageIndex
                ? "border-primary/30 bg-primary/10 text-primary"
                : "border-border/70 text-muted-foreground hover:text-foreground",
            )}
          >
            {page + 1}
          </button>
        ))}
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label="Página siguiente"
              className={BOTON_PAGINA}
              onClick={() => onPageChange(pageIndex + 1)}
              disabled={!canNext}
            >
              <ChevronRight className="h-3 w-3" aria-hidden="true" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Siguiente</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label="Última página"
              className={BOTON_PAGINA}
              onClick={() => onPageChange(totalPages - 1)}
              disabled={!(canLast ?? canNext)}
            >
              <ChevronsRight className="h-3 w-3" aria-hidden="true" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Última página</TooltipContent>
        </Tooltip>
      </nav>
    </div>
  );
}
