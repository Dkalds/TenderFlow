"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ChevronsUpDown, Search, Star, X } from "lucide-react";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { PanelError } from "@/components/console/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { PAGE_SIZE, type EmpresaRow, type EmpresaSortKey } from "../_hooks/use-maestro";

/** Rejilla compartida por la cabecera y las filas: una sola definición. */
const GRID = "grid grid-cols-[minmax(0,1fr)_100px_52px_84px_36px] items-center gap-2.5 px-4";

const COLUMNAS: { key: EmpresaSortKey; label: string; right?: boolean }[] = [
  { key: "nombre", label: "Empresa" },
  { key: "nif", label: "NIF" },
  { key: "contratos", label: "Nº", right: true },
  { key: "importe", label: "Importe", right: true },
];

export interface MaestroListProps {
  search: string;
  onSearchChange: (value: string) => void;
  /** La búsqueda llegó por `?q=` desde un grafo, no la ha escrito el usuario. */
  fromDeepLink: boolean;
  rows: EmpresaRow[];
  total: number;
  page: number;
  onPageChange: (page: number) => void;
  sortKey: EmpresaSortKey;
  sortDir: "asc" | "desc";
  onSort: (key: EmpresaSortKey) => void;
  selectedId: number | null;
  onSelect: (empresaId: number) => void;
  watchedIds: Set<number>;
  onToggleWatch: (empresaId: number, watched: boolean) => void;
  /** Hay un alta o baja de vigilancia en vuelo: no se aceptan más clics. */
  watchPending: boolean;
  loading: boolean;
  error: boolean;
  errorDetail?: string;
  onRetry: () => void;
}

export function MaestroList({
  search,
  onSearchChange,
  fromDeepLink,
  rows,
  total,
  page,
  onPageChange,
  sortKey,
  sortDir,
  onSort,
  selectedId,
  onSelect,
  watchedIds,
  onToggleWatch,
  watchPending,
  loading,
  error,
  errorDetail,
  onRetry,
}: MaestroListProps) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const desde = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const hasta = Math.min((page + 1) * PAGE_SIZE, total);

  return (
    <div className="border-border/60 flex w-[560px] flex-none flex-col border-r">
      {/* El buscador vive en la columna que busca. Estaba en la barra del
          espacio, encima de las dos vistas, así que seguía visible en la cola
          de revisión —donde no busca nada— y parecía global. */}
      <div className="border-border/60 flex flex-none items-center gap-2 border-b px-4 py-3">
        <div className="border-border/70 bg-background focus-within:border-primary/50 flex h-8 flex-1 items-center gap-2 rounded-lg border px-2.5">
          <Search className="text-muted-foreground h-3.5 w-3.5 flex-none" aria-hidden="true" />
          <input
            type="text"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Nombre, alias o NIF"
            aria-label="Buscar empresa"
            className="text-tf-body text-foreground placeholder:text-muted-foreground h-6 min-w-0 flex-1 border-0 bg-transparent outline-none"
          />
          {fromDeepLink && (
            <span
              title="Búsqueda recibida por ?q= desde un grafo"
              className="bg-primary/12 text-tf-micro text-primary flex h-5 flex-none items-center rounded px-1.5 font-mono font-medium"
            >
              desde grafo
            </span>
          )}
          {search && (
            <button
              type="button"
              onClick={() => onSearchChange("")}
              aria-label="Limpiar búsqueda"
              className="text-muted-foreground hover:text-foreground grid h-5 w-5 flex-none place-items-center rounded"
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      {error ? (
        // Error por bloque: el maestro cae, pero la cola de revisión viene de
        // otro endpoint y sigue siendo alcanzable desde el conmutador.
        <div className="p-4">
          <PanelError
            title="No se pudo cargar el maestro"
            detail={errorDetail ?? "GET /api/v1/empresas"}
            onRetry={onRetry}
          />
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className={cn(GRID, "border-border/70 bg-background sticky top-0 z-10 h-[34px] border-b")}>
              {COLUMNAS.map((columna) => {
                const on = columna.key === sortKey;
                const Icono = !on ? ChevronsUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;
                return (
                  <button
                    key={columna.key}
                    type="button"
                    onClick={() => onSort(columna.key)}
                    aria-label={`Ordenar por ${columna.label}`}
                    className={cn(
                      "text-tf-micro inline-flex h-5 items-center gap-1 font-medium whitespace-nowrap transition-colors duration-140 ease-out",
                      columna.right && "w-full justify-end",
                      on ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {columna.label}
                    <Icono className={cn("h-3 w-3 flex-none", !on && "opacity-35")} aria-hidden="true" />
                  </button>
                );
              })}
              <span className="text-tf-micro text-muted-foreground text-right font-medium">Vigilar</span>
            </div>

            {loading ? (
              <div className="flex flex-col gap-2 px-4 py-2.5">
                {Array.from({ length: 8 }, (_, i) => (
                  <Skeleton key={i} className="h-8 w-full rounded-md" />
                ))}
              </div>
            ) : rows.length === 0 ? (
              <EmptyState
                icon={Search}
                title="Sin resultados"
                hint="Prueba con otro nombre o NIF, o ejecuta el backfill del maestro para resolver los adjudicatarios pendientes."
              />
            ) : (
              rows.map((row) => {
                const on = row.empresa_id === selectedId;
                const watched = watchedIds.has(row.empresa_id);
                // UTE y PYME en gris y sin cápsula: eran dos chips de color
                // (violeta y verde) que sólo existían en esta pantalla y
                // competían con la selección por la atención de la fila.
                const marcas = [row.es_ute ? "UTE" : null, row.es_pyme ? "PYME" : null].filter(Boolean).join(" · ");
                return (
                  <div
                    key={row.empresa_id}
                    className={cn(
                      GRID,
                      "border-border/30 h-10 border-b transition-colors duration-140 ease-out",
                      on ? "bg-primary/8" : "hover:bg-muted-foreground/6",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => onSelect(row.empresa_id)}
                      aria-current={on ? "true" : undefined}
                      className="flex min-w-0 items-baseline gap-1.5 text-left"
                    >
                      <span
                        className={cn(
                          "text-tf-body min-w-0 truncate",
                          on ? "text-primary font-semibold" : "text-foreground font-medium",
                        )}
                      >
                        {row.nombre_canonico}
                      </span>
                      {marcas && (
                        <span className="text-tf-micro text-muted-foreground flex-none font-mono">{marcas}</span>
                      )}
                    </button>
                    <span className="text-tf-meta text-muted-foreground truncate font-mono">
                      {row.nif_canonico ?? "—"}
                    </span>
                    <span className="tf-tnum text-tf-meta text-muted-foreground text-right font-mono">
                      {formatNumber(row.n_adjudicaciones)}
                    </span>
                    <span className="tf-tnum text-tf-meta text-foreground text-right font-mono font-medium">
                      {formatCurrency(row.importe_total)}
                    </span>
                    <button
                      type="button"
                      onClick={() => onToggleWatch(row.empresa_id, watched)}
                      disabled={watchPending}
                      title={watched ? "Dejar de vigilar" : "Vigilar empresa"}
                      aria-label={watched ? "Dejar de vigilar" : "Vigilar empresa"}
                      aria-pressed={watched}
                      className={cn(
                        "tf-pressable grid h-7 w-7 place-items-center justify-self-end rounded-md transition-colors duration-140 ease-out",
                        watched ? "text-primary" : "text-muted-foreground/60 hover:text-foreground",
                      )}
                    >
                      <Star className="h-3.5 w-3.5" fill={watched ? "currentColor" : "none"} aria-hidden="true" />
                    </button>
                  </div>
                );
              })
            )}
          </div>

          {!loading && total > 0 && (
            <div className="border-border/60 flex flex-none items-center gap-2 border-t px-4 py-2.5">
              {/* El denominador es el total del filtro, que manda el servidor.
                  Antes se listaban 14 de 1.284 sin forma de ver la 15.
                  `agruparSiempre` porque las tres cifras se leen como una
                  serie: sin él, «1284» al lado de «12» son dos formatos. */}
              <span className="tf-tnum text-tf-meta text-muted-foreground">
                Mostrando {formatNumber(desde)}–{formatNumber(hasta)} de{" "}
                {formatNumber(total, "es-ES", { agruparSiempre: true })}
              </span>
              <div className="flex-1" />
              <PageButton onClick={() => onPageChange(page - 1)} disabled={page === 0} label="Página anterior">
                <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
              </PageButton>
              {ventanaDePaginas(page, pages).map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => onPageChange(n)}
                  aria-current={n === page ? "page" : undefined}
                  className={cn(
                    "tf-pressable tf-tnum text-tf-meta h-6.5 min-w-6.5 rounded-md border px-1.5 font-mono",
                    n === page
                      ? "border-primary/40 bg-primary/12 text-primary"
                      : "text-muted-foreground hover:text-foreground border-transparent",
                  )}
                >
                  {n + 1}
                </button>
              ))}
              <PageButton onClick={() => onPageChange(page + 1)} disabled={page >= pages - 1} label="Página siguiente">
                <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              </PageButton>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function PageButton({
  onClick,
  disabled,
  label,
  children,
}: {
  onClick: () => void;
  disabled: boolean;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className="tf-pressable border-border/70 text-muted-foreground hover:text-foreground disabled:border-border/25 disabled:text-muted-foreground/40 disabled:hover:text-muted-foreground/40 grid h-6.5 w-6.5 place-items-center rounded-md border transition-colors"
    >
      {children}
    </button>
  );
}

/**
 * Hasta siete números alrededor de la página actual.
 *
 * Con 1.284 empresas y 12 por página hay 107 páginas: pintarlas todas llena la
 * barra de números que nadie pulsa y empuja el contador fuera de la vista.
 */
export function ventanaDePaginas(page: number, pages: number, ancho = 7): number[] {
  if (pages <= ancho) return Array.from({ length: pages }, (_, i) => i);
  const mitad = Math.floor(ancho / 2);
  const inicio = Math.min(Math.max(0, page - mitad), pages - ancho);
  return Array.from({ length: ancho }, (_, i) => inicio + i);
}
