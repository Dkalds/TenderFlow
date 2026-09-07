"use client";

import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { SHORTCUTS } from "./detalle-columnas";

const BOTON_PAGINA =
  "tf-pressable grid h-6.5 w-6.5 place-items-center rounded-md border border-border/70 text-[12px] text-muted-foreground transition-colors duration-140 ease-out hover:text-foreground disabled:cursor-default disabled:opacity-35";

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
  onPageChange,
}: {
  showingLine: string;
  clientSorted: boolean;
  pageIndex: number;
  totalPages: number;
  pageWindow: number[];
  canPrevious: boolean;
  canNext: boolean;
  onPageChange: (page: number) => void;
}) {
  return (
    <div className="flex h-11 flex-none items-center gap-3 border-t border-border/70 bg-card/60 px-3.5">
      <span className="tf-tnum text-[11px] text-muted-foreground">{showingLine}</span>
      {clientSorted && (
        <span
          className="rounded border border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.12)] px-1.5 py-0.5 text-[10.5px] text-[hsl(var(--warning))]"
          title="El backend sólo ordena por título, importe y fecha; el resto se ordena sobre las filas ya cargadas."
        >
          orden sobre esta página
        </span>
      )}
      <div className="flex-1" />
      {SHORTCUTS.map((shortcut) => (
        <span
          key={shortcut.key}
          className="hidden items-center gap-1.5 text-[11px] text-muted-foreground xl:inline-flex"
        >
          <span className="rounded border border-border/70 px-1 py-0.5 font-mono text-[9px] font-medium">
            {shortcut.key}
          </span>
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
              "tf-tnum tf-pressable h-6.5 min-w-6.5 rounded-md border px-1 font-mono text-[11px] transition-colors duration-140 ease-out",
              page === pageIndex
                ? "border-primary/40 bg-primary/14 text-primary"
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
              disabled={!canNext}
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
