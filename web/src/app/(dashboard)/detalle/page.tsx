"use client";

import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { parseAsString, useQueryState } from "nuqs";
import { useQuery } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
  type PaginationState,
  type RowSelectionState,
} from "@tanstack/react-table";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { t } from "@/lib/i18n";
import { formatCurrency, formatDate, truncate, cn } from "@/lib/utils";
import { getJSON, setJSON } from "@/lib/storage";
import { useFilterParams, useFilters } from "@/lib/filters";
import { toggleValue } from "@/lib/chart-interaction";
import { DetailPanel, type LicitacionDetail } from "@/components/detail-panel";
import { Comparator } from "@/components/comparator";
import { ExportPopover } from "@/components/export-popover";
import type { LicitacionSummary } from "@/generated/api";
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Search,
  Download,
  X,
  Rows3,
  Rows2,
  Star,
  GitCompareArrows,
} from "lucide-react";

/* ── Types ──────────────────────────────────────────────────────────── */

interface LicitacionesResponse {
  items: LicitacionSummary[];
  total: number;
  limit: number;
  offset: number;
}

interface ScoringItem {
  id_externo: string;
  score: number;
  band: string;
  desglose: Record<string, number>;
}

interface ScoringResponse {
  opportunities: ScoringItem[];
}

/* ── Constants ──────────────────────────────────────────────────────── */

const PAGE_SIZE = 25;


const LAST_VIEWED_KEY = "detalle_last_viewed";
const COMPACT_KEY = "detalle_compact";
const WATCHLIST_KEY = "detalle_watchlist";

/* ── Helpers ────────────────────────────────────────────────────────── */

function getLastViewed(): number {
  return getJSON<number>(LAST_VIEWED_KEY, 0);
}

function getCompactPref(): boolean {
  return getJSON<boolean>(COMPACT_KEY, false);
}

function getWatchlist(): string[] {
  return getJSON<string[]>(WATCHLIST_KEY, []);
}

function downloadCsv(rows: LicitacionSummary[], filename: string) {
  const headers = ["id_externo", "titulo", "organo_contratacion", "importe", "estado", "fecha_publicacion", "ccaa", "cpv", "tecnologia"];
  const csv = [
    headers.join(","),
    ...rows.map((r) =>
      headers
        .map((h) => {
          const v = (r as unknown as Record<string, unknown>)[h];
          const s = v == null ? "" : String(v);
          return s.includes(",") || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s;
        })
        .join(","),
    ),
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/* ── Merged row type ────────────────────────────────────────────────── */

interface MergedRow extends LicitacionSummary {
  score?: number;
  band?: string;
  desglose?: Record<string, number>;
  isNew?: boolean;
}

/* ── Component ──────────────────────────────────────────────────────── */

export default function DetallePage() {
  const filterParams = useFilterParams();
  const { ccaas, setCcaas, tecnologias, setTecnologias } = useFilters();
  const toggleCcaa = useCallback(
    (ccaa: string) => setCcaas(toggleValue(ccaa, ccaas)),
    [ccaas, setCcaas],
  );
  const toggleTecnologia = useCallback(
    (tec: string) => setTecnologias(toggleValue(tec, tecnologias)),
    [tecnologias, setTecnologias],
  );

  // State
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: PAGE_SIZE,
  });
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  // Permalink del panel de detalle: ?lic=<id_externo>. Abrir hace push (el botón
  // atrás cierra el panel); URL compartible/bookmarkeable desde cualquier fila.
  const [detailId, setDetailId] = useQueryState(
    "lic",
    parseAsString.withOptions({ history: "push", shallow: true }),
  );
  const [showComparator, setShowComparator] = useState(false);
  const [compact, setCompact] = useState(getCompactPref);
  const [lastViewed] = useState(getLastViewed);

  // Mark last viewed on mount
  useEffect(() => {
    setJSON(LAST_VIEWED_KEY, Date.now());
  }, []);

  // Compact mode persistence
  useEffect(() => {
    setJSON(COMPACT_KEY, compact);
  }, [compact]);

  // Debounce search
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleSearchChange = useCallback((value: string) => {
    setSearch(value);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      setDebouncedSearch(value);
      setPagination((p) => ({ ...p, pageIndex: 0 }));
    }, 400);
  }, []);

  // Build query params
  const queryParams = useMemo(() => {
    const params: Record<string, string> = {
      ...filterParams,
      limit: String(pagination.pageSize),
      offset: String(pagination.pageIndex * pagination.pageSize),
    };
    if (debouncedSearch) params.q = debouncedSearch;
    if (sorting.length > 0) {
      params.sort_by = sorting[0].id;
      params.sort_order = sorting[0].desc ? "desc" : "asc";
    }
    return params;
  }, [pagination, debouncedSearch, sorting, filterParams]);

  // Fetch licitaciones
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ["licitaciones", queryParams],
    queryFn: async ({ signal }) => {
      const sp = new URLSearchParams(queryParams);
      const res = await fetch(`/api/v1/licitaciones?${sp}`, {
        credentials: "include",
        signal,
      });
      if (!res.ok) throw new Error(`Failed to fetch licitaciones: ${res.status}`);
      return res.json() as Promise<LicitacionesResponse>;
    },
    staleTime: 30_000,
    placeholderData: (prev) => prev,
    retry: 2,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
  });

  // Scoring alineado a la página: pedimos el score EXACTO de las filas visibles
  // (sus id_externo), no un top-500 global disjunto del orden/filtro/página. Antes
  // el score nunca aparecía: el merge leía `.items` pero el backend devuelve
  // `.opportunities`, y top-500 no solapaba con páginas avanzadas. ADR-014: el
  // backend es la fuente; el front solo alinea por id.
  const pageIds = useMemo(
    () => (data?.items ?? []).map((r) => r.id_externo).filter(Boolean),
    [data],
  );

  const { data: scoring } = useQuery({
    queryKey: ["scoring-batch", pageIds],
    queryFn: async ({ signal }) => {
      const sp = new URLSearchParams({ ids: pageIds.join(",") });
      const res = await fetch(`/api/v1/analytics/scoring?${sp}`, {
        credentials: "include",
        signal,
      });
      if (!res.ok) throw new Error(`Failed to fetch scoring: ${res.status}`);
      return res.json() as Promise<ScoringResponse>;
    },
    enabled: pageIds.length > 0,
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  });

  // Fetch detail for panel
  const { data: detailData } = useQuery({
    queryKey: ["licitacion", detailId],
    queryFn: async () => {
      const res = await fetch(`/api/v1/licitaciones/${detailId}`, { credentials: "include" });
      if (!res.ok) throw new Error("Failed to fetch detail");
      return res.json() as Promise<LicitacionDetail>;
    },
    enabled: !!detailId,
  });

  // Score map
  const scoreMap = useMemo(() => {
    const map = new Map<string, ScoringItem>();
    for (const item of scoring?.opportunities ?? []) {
      map.set(item.id_externo, item);
    }
    return map;
  }, [scoring]);

  // Merged rows
  const mergedRows = useMemo<MergedRow[]>(() => {
    return (data?.items ?? []).map((row) => {
      const sc = scoreMap.get(row.id_externo);
      const pub = row.fecha_publicacion ? new Date(row.fecha_publicacion).getTime() : 0;
      return {
        ...row,
        score: sc?.score,
        band: sc?.band,
        desglose: sc?.desglose,
        isNew: pub > lastViewed,
      };
    });
  }, [data, scoreMap, lastViewed]);

  // Cell sizing
  const cellPad = compact ? "px-2 py-1" : "px-3 py-2.5";
  const fontSize = compact ? "text-xs" : "text-sm";

  // Columns
  const columns = useMemo<ColumnDef<MergedRow>[]>(
    () => [
      {
        id: "select",
        size: 40,
        header: ({ table }) => (
          <Checkbox
            className="h-5 w-5"
            checked={table.getIsAllPageRowsSelected()}
            onCheckedChange={(checked) => table.getToggleAllPageRowsSelectedHandler()({ target: { checked } } as unknown as React.ChangeEvent<HTMLInputElement>)}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            className="h-5 w-5"
            checked={row.getIsSelected()}
            onCheckedChange={(checked) => row.getToggleSelectedHandler()({ target: { checked } } as unknown as React.ChangeEvent<HTMLInputElement>)}
            onClick={(e) => e.stopPropagation()}
          />
        ),
      },
      {
        id: "new_indicator",
        size: 30,
        header: "",
        cell: ({ row }) =>
          row.original.isNew ? (
            <span className="inline-block h-2 w-2 rounded-full bg-blue-500" title="Nuevo" />
          ) : null,
      },
      {
        accessorKey: "id_externo",
        header: "ID",
        size: 120,
        cell: ({ getValue }) => (
          <span className="font-mono text-xs">{truncate(getValue<string>(), 18)}</span>
        ),
      },
      {
        accessorKey: "titulo",
        header: "Titulo",
        size: 280,
        cell: ({ getValue }) => (
          <span title={getValue<string>() ?? ""}>{truncate(getValue<string>(), compact ? 45 : 60)}</span>
        ),
      },
      {
        accessorKey: "organo_contratacion",
        header: "Organo",
        size: 180,
        cell: ({ getValue }) => (
          <span title={getValue<string>() ?? ""}>{truncate(getValue<string>(), compact ? 30 : 40)}</span>
        ),
      },
      {
        accessorKey: "importe",
        header: "Importe",
        size: 120,
        cell: ({ getValue }) => (
          <span className="tabular-nums">{formatCurrency(getValue<number | null>())}</span>
        ),
      },
      {
        accessorKey: "estado",
        header: "Estado",
        size: 110,
        cell: ({ getValue }) => {
          const estado = getValue<string | null>();
          return <StatusBadge value={estado} kind="estado" showIcon />;
        },
      },
      {
        id: "score",
        header: "Score",
        size: 100,
        cell: ({ row }) => {
          const { band } = row.original;
          return <StatusBadge value={band} kind="band" showIcon />;
        },
      },
      {
        accessorKey: "fecha_publicacion",
        header: "Fecha",
        size: 110,
        cell: ({ getValue }) => (
          <span className="tabular-nums text-xs">{formatDate(getValue<string | null>())}</span>
        ),
      },
      {
        accessorKey: "ccaa",
        header: "CCAA",
        size: 120,
        cell: ({ getValue }) => {
          const ccaa = getValue<string>();
          if (!ccaa) return "-";
          return (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                toggleCcaa(ccaa);
              }}
              className={cn(
                "rounded px-1 text-left hover:underline",
                ccaas.includes(ccaa) && "font-semibold text-primary",
              )}
              title={`Filtrar por ${ccaa}`}
            >
              {truncate(ccaa, 20)}
            </button>
          );
        },
      },
      {
        accessorKey: "cpv",
        header: "CPV",
        size: 90,
        cell: ({ getValue }) => (
          <span className="font-mono text-xs">{getValue<string>() ?? "-"}</span>
        ),
      },
      {
        accessorKey: "tecnologia",
        header: "Tecnologia",
        size: 110,
        cell: ({ getValue }) => {
          const tech = getValue<string | null>();
          if (!tech) return "-";
          return (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                toggleTecnologia(tech);
              }}
              title={`Filtrar por ${tech}`}
            >
              <Badge
                variant={tecnologias.includes(tech) ? "default" : "outline"}
                className="cursor-pointer text-xs"
              >
                {tech}
              </Badge>
            </button>
          );
        },
      },
    ],
    [compact, ccaas, tecnologias, toggleCcaa, toggleTecnologia],
  );

  const totalPages = Math.ceil((data?.total ?? 0) / pagination.pageSize);

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: mergedRows,
    columns,
    state: { sorting, pagination, rowSelection },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
    pageCount: totalPages,
    getRowId: (row) => row.id_externo,
    enableRowSelection: true,
  });

  // Selected items
  const selectedIds = Object.keys(rowSelection).filter((k) => rowSelection[k]);
  const selectedItems = mergedRows.filter((r) => selectedIds.includes(r.id_externo));

  // Bulk actions
  const handleCompare = () => {
    if (selectedItems.length >= 2 && selectedItems.length <= 3) {
      setShowComparator(true);
    }
  };

  const handleExportSelection = () => {
    downloadCsv(selectedItems, `seleccion_${new Date().toISOString().slice(0, 10)}.csv`);
  };

  const handleFollow = () => {
    const current = getWatchlist();
    const newIds = selectedIds.filter((id) => !current.includes(id));
    setJSON(WATCHLIST_KEY, [...current, ...newIds]);
    setRowSelection({});
  };

  // Detail panel data with score merge
  const detailWithScore = useMemo<LicitacionDetail | null>(() => {
    if (!detailData) return null;
    const sc = scoreMap.get(detailData.id_externo);
    return {
      ...detailData,
      score: sc?.score,
      score_desglose: sc?.desglose,
    } as LicitacionDetail;
  }, [detailData, scoreMap]);

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">
          {t("common.error")}: {(error as Error).message}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Detalle</h1>
          <p className="text-muted-foreground">
            Tabla completa con todos los campos y exportacion.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setCompact((c) => !c)}
          title={compact ? "Vista normal" : "Vista compacta"}
        >
          {compact ? <Rows3 className="h-4 w-4" /> : <Rows2 className="h-4 w-4" />}
        </Button>
      </div>

      {/* Toolbar */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder={t("common.search") + "..."}
                value={search}
                onChange={(e) => handleSearchChange(e.target.value)}
                className="pl-8"
              />
              {search && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => { setSearch(""); setDebouncedSearch(""); }}
                  className="absolute right-1.5 top-1.5 h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <ExportPopover />
            </div>
          </div>

          {debouncedSearch && (
            <div className="flex items-center gap-2 mt-3 flex-wrap">
              <span className="text-xs text-muted-foreground">Filtros:</span>
              <Badge variant="secondary" className="text-xs">
                Busqueda: &quot;{debouncedSearch}&quot;
                <Button variant="ghost" size="sm" onClick={() => { setSearch(""); setDebouncedSearch(""); }} className="ml-1 h-auto p-0">
                  <X className="h-3 w-3" />
                </Button>
              </Badge>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className={cn("w-full", fontSize)}>
              <thead>
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id} className="border-b bg-muted/50">
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        className={cn(
                          cellPad,
                          "text-left font-medium text-muted-foreground whitespace-nowrap",
                          header.column.getCanSort() && "cursor-pointer select-none hover:text-foreground",
                        )}
                        style={{ width: header.getSize() }}
                        onClick={header.column.getToggleSortingHandler()}
                        tabIndex={header.column.getCanSort() ? 0 : undefined}
                        role="columnheader"
                        aria-sort={header.column.getIsSorted() === "asc" ? "ascending" : header.column.getIsSorted() === "desc" ? "descending" : "none"}
                        onKeyDown={(e) => { if (e.key === "Enter" && header.column.getCanSort()) header.column.getToggleSortingHandler()?.(e as unknown as React.MouseEvent); }}
                      >
                        <div className="flex items-center gap-1">
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {header.column.getCanSort() && (
                            header.column.getIsSorted() === "asc" ? (
                              <ArrowUp className="h-3.5 w-3.5" />
                            ) : header.column.getIsSorted() === "desc" ? (
                              <ArrowDown className="h-3.5 w-3.5" />
                            ) : (
                              <ArrowUpDown className="h-3.5 w-3.5 opacity-30" />
                            )
                          )}
                        </div>
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {isLoading ? (
                  Array.from({ length: PAGE_SIZE }).map((_, i) => (
                    <tr key={i} className="border-b">
                      {columns.map((_, ci) => (
                        <td key={ci} className={cellPad}>
                          <Skeleton className="h-5 w-full" />
                        </td>
                      ))}
                    </tr>
                  ))
                ) : table.getRowModel().rows.length === 0 ? (
                  <tr>
                    <td colSpan={columns.length} className="px-3 py-6">
                      <EmptyState />
                    </td>
                  </tr>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <tr
                      key={row.id}
                      className={cn(
                        "border-b hover:bg-muted/50 cursor-pointer transition-colors",
                        isFetching && "opacity-60",
                        row.getIsSelected() && "bg-primary/5",
                      )}
                      tabIndex={0}
                      role="row"
                      onClick={() => setDetailId(row.original.id_externo)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setDetailId(row.original.id_externo); }}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className={cellPad}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between px-4 py-3 border-t">
            <div className="text-xs text-muted-foreground">
              {data ? (
                <>
                  Mostrando {pagination.pageIndex * pagination.pageSize + 1}-
                  {Math.min((pagination.pageIndex + 1) * pagination.pageSize, data.total)}{" "}
                  de {data.total.toLocaleString("es-ES")} resultados
                </>
              ) : (
                <Skeleton className="h-4 w-40" />
              )}
            </div>

            <div className="flex items-center gap-1">
              <Button variant="outline" size="icon" className="h-9 w-9" onClick={() => table.setPageIndex(0)} disabled={!table.getCanPreviousPage()}>
                <ChevronsLeft className="h-4 w-4" />
              </Button>
              <Button variant="outline" size="icon" className="h-9 w-9" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              {(() => {
                const pages: number[] = [];
                const current = pagination.pageIndex;
                const start = Math.max(0, current - 2);
                const end = Math.min(totalPages - 1, current + 2);
                for (let i = start; i <= end; i++) pages.push(i);
                return pages.map((page) => (
                  <Button
                    key={page}
                    variant={page === current ? "default" : "outline"}
                    size="icon"
                    className="h-9 w-9 text-xs"
                    onClick={() => table.setPageIndex(page)}
                  >
                    {page + 1}
                  </Button>
                ));
              })()}
              <Button variant="outline" size="icon" className="h-9 w-9" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button variant="outline" size="icon" className="h-9 w-9" onClick={() => table.setPageIndex(totalPages - 1)} disabled={!table.getCanNextPage()}>
                <ChevronsRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Floating bulk-action toolbar */}
      {selectedIds.length > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 flex items-center gap-2 rounded-lg border bg-background px-4 py-3 shadow-lg">
          <span className="text-sm font-medium mr-2">{selectedIds.length} seleccionados</span>
          <Button
            variant="outline"
            size="sm"
            onClick={handleCompare}
            disabled={selectedIds.length < 2 || selectedIds.length > 3}
          >
            <GitCompareArrows className="h-4 w-4 mr-1" />
            Comparar ({selectedIds.length})
          </Button>
          <Button variant="outline" size="sm" onClick={handleExportSelection}>
            <Download className="h-4 w-4 mr-1" />
            Exportar seleccion
          </Button>
          <Button variant="outline" size="sm" onClick={handleFollow}>
            <Star className="h-4 w-4 mr-1" />
            Seguir
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setRowSelection({})}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}

      {/* Detail Panel */}
      {detailId && detailWithScore && (
        <DetailPanel
          licitacion={detailWithScore}
          onClose={() => setDetailId(null, { history: "replace" })}
        />
      )}

      {/* Comparator */}
      {showComparator && selectedItems.length >= 2 && (
        <Comparator
          items={selectedItems.map((r) => ({
            id_externo: r.id_externo,
            titulo: r.titulo,
            organo_contratacion: r.organo_contratacion,
            importe: r.importe,
            estado: r.estado,
            fecha_publicacion: r.fecha_publicacion,
            ccaa: r.ccaa,
            cpv: r.cpv,
            url: r.url,
            tecnologia: r.tecnologia,
            tipo_contrato: null,
            provincia: null,
            fecha_limite: null,
            fecha_inicio: null,
            fecha_fin: null,
            descripcion: null,
            score: r.score,
          }))}
          onClose={() => setShowComparator(false)}
        />
      )}
    </div>
  );
}
