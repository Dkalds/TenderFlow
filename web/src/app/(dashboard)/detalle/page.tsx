"use client";

import { useMemo, useState, useCallback, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
  type PaginationState,
} from "@tanstack/react-table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { t } from "@/lib/i18n";
import { formatCurrency, formatDate, truncate, cn } from "@/lib/utils";
import type { LicitacionSummary } from "@/generated/api";
import {
  Table,
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
  ChevronDown,
  Loader2,
  FileText,
  FileSpreadsheet,
  File,
} from "lucide-react";

interface LicitacionesResponse {
  items: LicitacionSummary[];
  total: number;
  limit: number;
  offset: number;
}

interface FiltersResponse {
  estados: string[];
  ccaas: string[];
  tecnologias: string[];
  cpvs: string[];
}

async function fetchLicitaciones(params: Record<string, string>): Promise<LicitacionesResponse> {
  const searchParams = new URLSearchParams(params);
  const res = await fetch(`/api/v1/licitaciones?${searchParams}`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch licitaciones");
  return res.json();
}

async function fetchFilters(): Promise<FiltersResponse> {
  const res = await fetch("/api/v1/meta/filters", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch filters");
  return res.json();
}

const PAGE_SIZE = 25;

const ESTADO_COLORS: Record<string, string> = {
  Publicada: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300",
  Adjudicada: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300",
  Resuelta: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-300",
  Desierta: "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-300",
  Anulada: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300",
};

export default function DetallePage() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [estadoFilter, setEstadoFilter] = useState("");
  const [ccaaFilter, setCcaaFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: PAGE_SIZE,
  });

  // Debounce search
  const searchTimerRef = useMemo(() => ({ current: null as ReturnType<typeof setTimeout> | null }), []);
  const handleSearchChange = useCallback(
    (value: string) => {
      setSearch(value);
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
      searchTimerRef.current = setTimeout(() => {
        setDebouncedSearch(value);
        setPagination((p) => ({ ...p, pageIndex: 0 }));
      }, 400);
    },
    [searchTimerRef],
  );

  // Build query params
  const queryParams = useMemo(() => {
    const params: Record<string, string> = {
      limit: String(pagination.pageSize),
      offset: String(pagination.pageIndex * pagination.pageSize),
    };
    if (debouncedSearch) params.q = debouncedSearch;
    if (estadoFilter) params.estado = estadoFilter;
    if (ccaaFilter) params.ccaa = ccaaFilter;
    if (sorting.length > 0) {
      params.sort_by = sorting[0].id;
      params.sort_order = sorting[0].desc ? "desc" : "asc";
    }
    return params;
  }, [pagination, debouncedSearch, estadoFilter, ccaaFilter, sorting]);

  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ["licitaciones", queryParams],
    queryFn: () => fetchLicitaciones(queryParams),
    staleTime: 30 * 1000,
    placeholderData: (prev) => prev, // keep previous data while fetching
  });

  const { data: filters } = useQuery({
    queryKey: ["meta", "filters"],
    queryFn: fetchFilters,
    staleTime: 10 * 60 * 1000,
  });

  const columns = useMemo<ColumnDef<LicitacionSummary>[]>(
    () => [
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
        size: 300,
        cell: ({ getValue }) => (
          <span title={getValue<string>() ?? ""}>
            {truncate(getValue<string>(), 60)}
          </span>
        ),
      },
      {
        accessorKey: "organo_contratacion",
        header: "Organo",
        size: 200,
        cell: ({ getValue }) => (
          <span title={getValue<string>() ?? ""}>
            {truncate(getValue<string>(), 40)}
          </span>
        ),
      },
      {
        accessorKey: "importe",
        header: "Importe",
        size: 130,
        cell: ({ getValue }) => (
          <span className="tabular-nums">{formatCurrency(getValue<number | null>())}</span>
        ),
      },
      {
        accessorKey: "estado",
        header: "Estado",
        size: 120,
        cell: ({ getValue }) => {
          const estado = getValue<string | null>();
          if (!estado) return "-";
          return (
            <Badge
              variant="secondary"
              className={cn("text-xs", ESTADO_COLORS[estado] ?? "")}
            >
              {estado}
            </Badge>
          );
        },
      },
      {
        accessorKey: "fecha_publicacion",
        header: "Fecha",
        size: 120,
        cell: ({ getValue }) => (
          <span className="tabular-nums text-xs">
            {formatDate(getValue<string | null>())}
          </span>
        ),
      },
      {
        accessorKey: "ccaa",
        header: "CCAA",
        size: 130,
        cell: ({ getValue }) => truncate(getValue<string>(), 20),
      },
      {
        accessorKey: "cpv",
        header: "CPV",
        size: 100,
        cell: ({ getValue }) => (
          <span className="font-mono text-xs">{getValue<string>() ?? "-"}</span>
        ),
      },
      {
        accessorKey: "tecnologia",
        header: "Tecnologia",
        size: 120,
        cell: ({ getValue }) => {
          const tech = getValue<string | null>();
          return tech ? <Badge variant="outline" className="text-xs">{tech}</Badge> : "-";
        },
      },
    ],
    [],
  );

  const totalPages = Math.ceil((data?.total ?? 0) / pagination.pageSize);

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    state: { sorting, pagination },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
    pageCount: totalPages,
  });

  const handleRowClick = (row: LicitacionSummary) => {
    if (row.url) {
      window.open(row.url, "_blank", "noopener,noreferrer");
    }
  };

  const [exporting, setExporting] = useState(false);
  const [exportDropdownOpen, setExportDropdownOpen] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);

  const handleExport = async (format: "csv" | "excel" | "pdf") => {
    setExportDropdownOpen(false);
    if (format === "pdf") {
      setExporting(true);
      try {
        const body: Record<string, string> = {};
        if (debouncedSearch) body.q = debouncedSearch;
        if (estadoFilter) body.estado = estadoFilter;
        if (ccaaFilter) body.ccaa = ccaaFilter;
        const res = await fetch("/api/v1/exports", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error("Failed to create export job");
        const { id } = await res.json();
        let status = "pending";
        while (status !== "done") {
          await new Promise((r) => setTimeout(r, 1000));
          const poll = await fetch(`/api/v1/exports/${id}`, { credentials: "include" });
          if (poll.headers.get("content-type")?.includes("application/pdf")) {
            const blob = await poll.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `licitaciones_${new Date().toISOString().slice(0, 10)}.pdf`;
            a.click();
            URL.revokeObjectURL(url);
            status = "done";
          } else {
            const data = await poll.json();
            status = data.status;
            if (status === "error") throw new Error("PDF generation failed");
          }
        }
      } finally {
        setExporting(false);
      }
    } else {
      const params = new URLSearchParams();
      params.set("format", format);
      if (debouncedSearch) params.set("q", debouncedSearch);
      if (estadoFilter) params.set("estado", estadoFilter);
      if (ccaaFilter) params.set("ccaa", ccaaFilter);
      window.open(`/api/v1/exports/download?${params.toString()}`);
    }
  };

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="text-destructive">
          {t("common.error")}: {(error as Error).message}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Detalle</h1>
        <p className="text-muted-foreground">
          Tabla completa con todos los campos y exportacion.
        </p>
      </div>

      {/* Toolbar */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            {/* Search */}
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder={t("common.search") + "..."}
                value={search}
                onChange={(e) => handleSearchChange(e.target.value)}
                className="pl-8"
              />
              {search && (
                <button
                  onClick={() => { setSearch(""); setDebouncedSearch(""); }}
                  className="absolute right-2.5 top-2.5 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            {/* Filters */}
            <div className="flex items-center gap-2 flex-wrap">
              <select
                className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={estadoFilter}
                onChange={(e) => {
                  setEstadoFilter(e.target.value);
                  setPagination((p) => ({ ...p, pageIndex: 0 }));
                }}
              >
                <option value="">Todos los estados</option>
                {(filters?.estados ?? []).map((e) => (
                  <option key={e} value={e}>{e}</option>
                ))}
              </select>

              <select
                className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={ccaaFilter}
                onChange={(e) => {
                  setCcaaFilter(e.target.value);
                  setPagination((p) => ({ ...p, pageIndex: 0 }));
                }}
              >
                <option value="">Todas las CCAA</option>
                {(filters?.ccaas ?? []).map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>

              <div className="relative" ref={exportRef}>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setExportDropdownOpen((o) => !o)}
                  disabled={exporting}
                >
                  {exporting ? (
                    <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  ) : (
                    <Download className="h-4 w-4 mr-1" />
                  )}
                  {exporting ? "Exportando..." : t("common.export")}
                  <ChevronDown className="h-3 w-3 ml-1" />
                </Button>
                {exportDropdownOpen && (
                  <div className="absolute right-0 top-full mt-1 z-50 w-44 rounded-md border bg-popover shadow-md">
                    <button
                      className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
                      onClick={() => handleExport("csv")}
                    >
                      <FileText className="h-4 w-4" /> CSV
                    </button>
                    <button
                      className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
                      onClick={() => handleExport("excel")}
                    >
                      <FileSpreadsheet className="h-4 w-4" /> Excel
                    </button>
                    <button
                      className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted border-t"
                      onClick={() => handleExport("pdf")}
                    >
                      <File className="h-4 w-4" /> PDF
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Active filters */}
          {(debouncedSearch || estadoFilter || ccaaFilter) && (
            <div className="flex items-center gap-2 mt-3 flex-wrap">
              <span className="text-xs text-muted-foreground">Filtros:</span>
              {debouncedSearch && (
                <Badge variant="secondary" className="text-xs">
                  Busqueda: &quot;{debouncedSearch}&quot;
                  <button onClick={() => { setSearch(""); setDebouncedSearch(""); }} className="ml-1">
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              )}
              {estadoFilter && (
                <Badge variant="secondary" className="text-xs">
                  Estado: {estadoFilter}
                  <button onClick={() => setEstadoFilter("")} className="ml-1">
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              )}
              {ccaaFilter && (
                <Badge variant="secondary" className="text-xs">
                  CCAA: {ccaaFilter}
                  <button onClick={() => setCcaaFilter("")} className="ml-1">
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id} className="border-b bg-muted/50">
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        className={cn(
                          "px-3 py-2.5 text-left font-medium text-muted-foreground whitespace-nowrap",
                          header.column.getCanSort() && "cursor-pointer select-none hover:text-foreground",
                        )}
                        style={{ width: header.getSize() }}
                        onClick={header.column.getToggleSortingHandler()}
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
                        <td key={ci} className="px-3 py-2.5">
                          <Skeleton className="h-5 w-full" />
                        </td>
                      ))}
                    </tr>
                  ))
                ) : table.getRowModel().rows.length === 0 ? (
                  <tr>
                    <td
                      colSpan={columns.length}
                      className="px-3 py-12 text-center text-muted-foreground"
                    >
                      {t("common.no_data")}
                    </td>
                  </tr>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <tr
                      key={row.id}
                      className={cn(
                        "border-b hover:bg-muted/50 cursor-pointer transition-colors",
                        isFetching && "opacity-60",
                      )}
                      onClick={() => handleRowClick(row.original)}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-3 py-2.5">
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
                  {Math.min(
                    (pagination.pageIndex + 1) * pagination.pageSize,
                    data.total,
                  )}{" "}
                  de {data.total.toLocaleString("es-ES")} resultados
                </>
              ) : (
                <Skeleton className="h-4 w-40" />
              )}
            </div>

            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="icon"
                className="h-8 w-8"
                onClick={() => table.setPageIndex(0)}
                disabled={!table.getCanPreviousPage()}
              >
                <ChevronsLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="icon"
                className="h-8 w-8"
                onClick={() => table.previousPage()}
                disabled={!table.getCanPreviousPage()}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>

              {/* Page numbers */}
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
                    className="h-8 w-8 text-xs"
                    onClick={() => table.setPageIndex(page)}
                  >
                    {page + 1}
                  </Button>
                ));
              })()}

              <Button
                variant="outline"
                size="icon"
                className="h-8 w-8"
                onClick={() => table.nextPage()}
                disabled={!table.getCanNextPage()}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="icon"
                className="h-8 w-8"
                onClick={() => table.setPageIndex(totalPages - 1)}
                disabled={!table.getCanNextPage()}
              >
                <ChevronsRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
