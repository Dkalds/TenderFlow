"use client";

import { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import { parseAsString, useQueryState } from "nuqs";
import { useQuery } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  type PaginationState,
  type RowSelectionState,
  type SortingState,
} from "@tanstack/react-table";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Download,
  GitCompareArrows,
  Star,
  X,
} from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { StatusBadge } from "@/components/ui/status-badge";
import { ExportPopover } from "@/components/export-popover";
import { Comparator } from "@/components/comparator";
import { DetailInspector } from "@/components/detail-inspector";
import type { LicitacionDetail } from "@/components/detail-panel";
import { cn, formatCurrency, formatDate, formatNumber, truncate } from "@/lib/utils";
import { getJSON, setJSON, remove as removeStored } from "@/lib/storage";
import { useDensity } from "@/lib/density";
import { useFilterParams, useFilters } from "@/lib/filters";
import { toggleValue } from "@/lib/chart-interaction";
import {
  useAddWatchlistItem,
  useRemoveWatchlistItem,
  useWatchlistItems,
} from "@/hooks/use-watchlist-items";
import type { LicitacionSummary } from "@/lib/api-types";
import { bandColor, shortEur } from "../radar/_components/radar-shared";

/**
 * Detalle — tabla de trabajo con inspector en el mismo plano.
 *
 * La pantalla mantiene sus 28 capacidades; lo que cambia es dónde vive la
 * ficha. Antes era un Sheet modal que apilaba once bloques encima de la tabla,
 * así que comparar dos licitaciones exigía abrir, leer, cerrar y volver a
 * abrir. Ahora el inspector (`components/detail-inspector.tsx`) convive con la
 * tabla y reparte esos once bloques en cinco pestañas.
 *
 * La tabla conserva las trece columnas, el orden asc/desc/none con cabecera
 * pegajosa, la selección múltiple con select-all, el punto de «nueva», la
 * estrella de watchlist, el cross-filter desde CCAA y Tecnología, la densidad,
 * la paginación completa con contador, la exportación y los estados de carga,
 * vacío y error.
 */

/* ── Tipos ──────────────────────────────────────────────────────────── */

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

interface MergedRow extends LicitacionSummary {
  score?: number;
  band?: string;
  desglose?: Record<string, number>;
  isNew?: boolean;
}

/* ── Constantes ─────────────────────────────────────────────────────── */

const PAGE_SIZE = 25;
const LAST_VIEWED_KEY = "detalle_last_viewed";
const WATCHLIST_KEY = "detalle_watchlist";

/**
 * Anchos de las trece columnas. `table-layout: fixed` + `<colgroup>`: la rejilla
 * del diseño sin renunciar a una `<table>` real, que es lo que un lector de
 * pantalla necesita para anunciar «columna Importe, fila 4 de 25».
 */
const COLUMNS: { key: string; label: string; width: string; sortable?: boolean; align?: "right" }[] =
  [
    { key: "select", label: "", width: "34px" },
    { key: "new", label: "", width: "14px" },
    { key: "fav", label: "", width: "26px" },
    { key: "id_externo", label: "ID", width: "104px", sortable: true },
    { key: "titulo", label: "Título", width: "auto", sortable: true },
    { key: "organo_contratacion", label: "Órgano", width: "156px", sortable: true },
    { key: "importe", label: "Importe", width: "108px", sortable: true, align: "right" },
    { key: "estado", label: "Estado", width: "104px", sortable: true },
    { key: "score", label: "Score", width: "100px", sortable: true },
    { key: "fecha_publicacion", label: "Fecha", width: "86px", sortable: true, align: "right" },
    { key: "ccaa", label: "CCAA", width: "108px", sortable: true },
    { key: "cpv", label: "CPV", width: "82px", sortable: true },
    { key: "tecnologia", label: "Tecnología", width: "114px", sortable: true },
  ];

const TABLE_MIN_WIDTH = 1246;

/**
 * Columnas que el backend sabe ordenar, y el valor de `sort` que espera.
 *
 * `GET /licitaciones` acepta `sort` con seis valores (`db/repositories/
 * licitaciones.py::_SORT_MAP`) y **descarta en silencio cualquier otro**. La
 * tabla enviaba `sort_by`/`sort_order`, que ese endpoint no lee: la cabecera
 * pintaba su flecha y las filas no se movían. Las tres columnas de aquí se
 * ordenan en servidor sobre el total; el resto se ordena en cliente sobre la
 * página cargada, y la tabla lo dice en vez de fingir un orden global.
 */
const SERVER_SORT: Record<string, string> = {
  titulo: "titulo",
  importe: "importe",
  fecha_publicacion: "fecha_publicacion",
};

const SHORTCUTS = [
  { key: "J K", label: "recorrer" },
  { key: "⏎", label: "abrir ficha" },
  { key: "S", label: "favorito" },
  { key: "Esc", label: "cerrar" },
];

/* ── Utilidades ─────────────────────────────────────────────────────── */

function getWatchlist(): string[] {
  // Lado lector de la migración one-shot a servidor: la clave se vacía tras
  // subirla. Corrige el patrón ADR-014 §2, no es una instancia de él.
  // fdi-allow:client-state
  return getJSON<string[]>(WATCHLIST_KEY, []);
}

function downloadCsv(rows: LicitacionSummary[], filename: string) {
  const headers = [
    "id_externo",
    "titulo",
    "organo_contratacion",
    "importe",
    "estado",
    "fecha_publicacion",
    "ccaa",
    "cpv",
    "tecnologia",
  ];
  const csv = [
    headers.join(","),
    ...rows.map((row) =>
      headers
        .map((header) => {
          const value = (row as unknown as Record<string, unknown>)[header];
          const text = value == null ? "" : String(value);
          return text.includes(",") || text.includes('"')
            ? `"${text.replace(/"/g, '""')}"`
            : text;
        })
        .join(","),
    ),
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

/* ── Pantalla ───────────────────────────────────────────────────────── */

export default function DetallePage() {
  const filterParams = useFilterParams();
  const { q, ccaas, setCcaas, tecnologias, setTecnologias, resetFilters } = useFilters();
  const toggleCcaa = useCallback((ccaa: string) => setCcaas(toggleValue(ccaa, ccaas)), [ccaas, setCcaas]);
  const toggleTecnologia = useCallback(
    (tec: string) => setTecnologias(toggleValue(tec, tecnologias)),
    [tecnologias, setTecnologias],
  );

  const [sorting, setSorting] = useState<SortingState>([]);
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: PAGE_SIZE,
  });
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  // Permalink de la ficha: ?lic=<id_externo>, con push al historial (atrás
  // cierra el inspector) y URL compartible desde cualquier fila.
  const [detailId, setDetailId] = useQueryState(
    "lic",
    parseAsString.withOptions({ history: "push", shallow: true }),
  );
  const [showComparator, setShowComparator] = useState(false);
  const [cursor, setCursor] = useState(0);
  const { compact, toggleCompact } = useDensity();
  const [lastViewed] = useState(() => getJSON<number>(LAST_VIEWED_KEY, 0));
  const addWatchlistItem = useAddWatchlistItem();
  const removeWatchlistItem = useRemoveWatchlistItem();
  const { data: watched = [] } = useWatchlistItems();
  const watchedIds = useMemo(() => new Set(watched.map((item) => item.id_externo)), [watched]);

  useEffect(() => {
    setJSON(LAST_VIEWED_KEY, Date.now());
  }, []);

  // Migración one-shot: favoritos que vivían sólo en localStorage pasan al
  // servidor (ADR-014 §2); la clave se borra tras migrar para no repetir.
  useEffect(() => {
    const legacy = getWatchlist();
    if (legacy.length === 0) return;
    legacy.forEach((id) => addWatchlistItem.mutate(id));
    removeStored(WATCHLIST_KEY);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- migración única al montar
  }, []);

  // La búsqueda global vive en la barra de ámbito; al cambiar, se vuelve a la
  // primera página, porque «página 7 de otro criterio» no significa nada.
  useEffect(() => {
    setPagination((current) => (current.pageIndex === 0 ? current : { ...current, pageIndex: 0 }));
  }, [q]);

  const queryParams = useMemo(() => {
    const params: Record<string, string> = {
      ...filterParams,
      limit: String(pagination.pageSize),
      offset: String(pagination.pageIndex * pagination.pageSize),
    };
    const active = sorting[0];
    const serverKey = active ? SERVER_SORT[active.id] : undefined;
    if (active && serverKey) {
      // El prefijo `-` invierte el sentido por defecto de cada columna: para
      // fecha el default es descendente y para importe/título ascendente.
      const defaultIsDesc = serverKey === "fecha_publicacion";
      params.sort = active.desc === defaultIsDesc ? serverKey : `-${serverKey}`;
    }
    return params;
  }, [pagination, sorting, filterParams]);

  const { data, isLoading, error, isFetching, refetch } = useQuery({
    queryKey: ["licitaciones", queryParams],
    queryFn: async ({ signal }) => {
      const search = new URLSearchParams(queryParams);
      const res = await fetch(`/api/v1/licitaciones?${search}`, {
        credentials: "include",
        signal,
      });
      if (!res.ok) throw new Error(`Failed to fetch licitaciones: ${res.status}`);
      return res.json() as Promise<LicitacionesResponse>;
    },
    staleTime: 30_000,
    placeholderData: (previous) => previous,
    retry: 2,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
  });

  // Scoring alineado a la página: se pide el score exacto de las filas visibles
  // (sus id_externo), no un top-500 global disjunto del orden y del filtro.
  const pageIds = useMemo(
    () => (data?.items ?? []).map((row) => row.id_externo).filter(Boolean),
    [data],
  );

  const { data: scoring } = useQuery({
    queryKey: ["scoring-batch", pageIds],
    queryFn: async ({ signal }) => {
      const search = new URLSearchParams({ ids: pageIds.join(",") });
      const res = await fetch(`/api/v1/analytics/scoring?${search}`, {
        credentials: "include",
        signal,
      });
      if (!res.ok) throw new Error(`Failed to fetch scoring: ${res.status}`);
      return res.json() as Promise<ScoringResponse>;
    },
    enabled: pageIds.length > 0,
    staleTime: 5 * 60_000,
    placeholderData: (previous) => previous,
  });

  const { data: detailData } = useQuery({
    queryKey: ["licitacion", detailId],
    queryFn: async () => {
      const res = await fetch(`/api/v1/licitaciones/${encodeURIComponent(detailId!)}`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to fetch detail");
      return res.json() as Promise<LicitacionDetail>;
    },
    enabled: !!detailId,
  });

  const scoreMap = useMemo(() => {
    const map = new Map<string, ScoringItem>();
    for (const item of scoring?.opportunities ?? []) map.set(item.id_externo, item);
    return map;
  }, [scoring]);

  const activeSort = sorting[0];
  // Orden en cliente sólo para las columnas que el backend no sabe ordenar.
  // Es un orden sobre la página cargada, no sobre el total, y el pie lo dice.
  const clientSorted = Boolean(activeSort && !SERVER_SORT[activeSort.id]);

  const mergedRows = useMemo<MergedRow[]>(() => {
    const rows = (data?.items ?? []).map((row) => {
      const scored = scoreMap.get(row.id_externo);
      const published = row.fecha_publicacion ? new Date(row.fecha_publicacion).getTime() : 0;
      return {
        ...row,
        score: scored?.score,
        band: scored?.band,
        desglose: scored?.desglose,
        isNew: published > lastViewed,
      };
    });

    if (!activeSort || SERVER_SORT[activeSort.id]) return rows;

    const key = activeSort.id as keyof MergedRow;
    return rows.sort((a, b) => {
      const left = a[key];
      const right = b[key];
      if (left == null && right == null) return 0;
      if (left == null) return 1;
      if (right == null) return -1;
      const compared =
        typeof left === "number" && typeof right === "number"
          ? left - right
          : String(left).localeCompare(String(right), "es", { sensitivity: "base" });
      return activeSort.desc ? -compared : compared;
    });
  }, [data, scoreMap, lastViewed, activeSort]);

  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / pagination.pageSize));

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: mergedRows,
    columns: useMemo(() => COLUMNS.map((column) => ({ id: column.key })), []),
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

  const selectedIds = Object.keys(rowSelection).filter((key) => rowSelection[key]);
  const selectedItems = mergedRows.filter((row) => selectedIds.includes(row.id_externo));
  const allPageSelected = mergedRows.length > 0 && mergedRows.every((row) => rowSelection[row.id_externo]);

  const toggleAllPage = () => {
    setRowSelection((current) => {
      const next = { ...current };
      for (const row of mergedRows) {
        if (allPageSelected) delete next[row.id_externo];
        else next[row.id_externo] = true;
      }
      return next;
    });
  };

  const toggleRow = (id: string) => {
    setRowSelection((current) => {
      const next = { ...current };
      if (next[id]) delete next[id];
      else next[id] = true;
      return next;
    });
  };

  const toggleSort = (columnId: string) => {
    setSorting((current) => {
      const active = current[0];
      // asc → desc → sin orden, el ciclo que ya tenía la tabla.
      if (!active || active.id !== columnId) return [{ id: columnId, desc: false }];
      if (!active.desc) return [{ id: columnId, desc: true }];
      return [];
    });
  };

  const toggleFavorite = (id: string) => {
    if (watchedIds.has(id)) removeWatchlistItem.mutate(id);
    else addWatchlistItem.mutate(id);
  };

  const openDetail = useCallback(
    (id: string) => {
      void setDetailId(id);
    },
    [setDetailId],
  );

  const closeDetail = useCallback(() => {
    // startTransition: cerrar desmonta bloques pesados (IA, documentos,
    // eventos); diferirlo evita bloquear el hilo principal en el propio clic.
    startTransition(() => {
      void setDetailId(null, { history: "replace" });
    });
  }, [setDetailId]);

  // Teclado de la tabla: J/K recorren, ⏎ abre la ficha, S marca favorito,
  // Esc cierra. Se ignora si el foco está en un campo de texto.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "Escape") {
        if (showComparator) setShowComparator(false);
        else if (detailId) closeDetail();
        return;
      }
      if (!mergedRows.length) return;
      const key = event.key.toLowerCase();
      const current = mergedRows[Math.min(cursor, mergedRows.length - 1)];
      if (key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        setCursor((index) => Math.min(index + 1, mergedRows.length - 1));
      } else if (key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        setCursor((index) => Math.max(index - 1, 0));
      } else if (key === "s") {
        event.preventDefault();
        if (current) toggleFavorite(current.id_externo);
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (current) openDetail(current.id_externo);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- toggleFavorite se redefine cada render
  }, [mergedRows, cursor, detailId, showComparator, closeDetail, openDetail]);

  // La fila del cursor se mantiene a la vista al recorrer con teclado.
  useEffect(() => {
    document
      .querySelector<HTMLElement>('[data-detalle-row="cursor"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const detailWithScore = useMemo<LicitacionDetail | null>(() => {
    if (!detailData) return null;
    const scored = scoreMap.get(detailData.id_externo);
    return {
      ...detailData,
      score: scored?.score,
      band: scored?.band ?? null,
      score_desglose: scored?.desglose,
    } as LicitacionDetail;
  }, [detailData, scoreMap]);

  const rowHeight = compact ? 34 : 44;
  const isEmpty = !isLoading && !error && mergedRows.length === 0;

  const pageWindow = useMemo(() => {
    const pages: number[] = [];
    const start = Math.max(0, pagination.pageIndex - 2);
    const end = Math.min(totalPages - 1, pagination.pageIndex + 2);
    for (let index = start; index <= end; index += 1) pages.push(index);
    return pages;
  }, [pagination.pageIndex, totalPages]);

  const sortLabel = sorting.length
    ? `${COLUMNS.find((column) => column.key === sorting[0].id)?.label ?? sorting[0].id} ${
        sorting[0].desc ? "↓" : "↑"
      }`
    : null;

  const showingLine = data
    ? `Mostrando ${pagination.pageIndex * pagination.pageSize + 1}–${Math.min(
        (pagination.pageIndex + 1) * pagination.pageSize,
        data.total,
      )} de ${formatNumber(data.total)}`
    : "—";

  const pageButton =
    "tf-pressable grid h-6.5 w-6.5 place-items-center rounded-md border border-border/70 text-[12px] text-muted-foreground transition-colors duration-140 ease-out hover:text-foreground disabled:cursor-default disabled:opacity-35";

  return (
    <div className="flex h-[calc(100vh-52px)] min-h-0">
      <section className="flex min-w-0 flex-1 flex-col border-r border-border/70">
        {/* Barra de la tabla */}
        <div className="flex h-11 flex-none items-center gap-2.5 border-b border-border/60 px-3.5">
          <span className="text-[12.5px] font-semibold">Detalle</span>
          <span className="hidden text-[11.5px] text-muted-foreground lg:inline">
            Tabla completa con todos los campos y exportación
          </span>
          <div className="flex-1" />
          {sortLabel && (
            <button
              type="button"
              onClick={() => setSorting([])}
              className="tf-pressable inline-flex h-6 items-center gap-1.5 rounded-md border border-primary/26 bg-primary/10 px-2 text-[11px] font-medium text-primary transition-colors duration-140 ease-out hover:bg-primary/20"
            >
              {sortLabel}
              <span className="opacity-60">×</span>
            </button>
          )}
          <div className="flex items-center gap-0.5 rounded-md border border-border/70 p-0.5">
            {[
              { key: false, label: "Cómoda" },
              { key: true, label: "Compacta" },
            ].map((option) => (
              <button
                key={String(option.key)}
                type="button"
                onClick={() => {
                  if (compact !== option.key) toggleCompact();
                }}
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

        {/* Tabla */}
        <div className="min-h-0 flex-1 overflow-auto">
          <div style={{ minWidth: TABLE_MIN_WIDTH }}>
            <table className="w-full table-fixed border-collapse">
              <colgroup>
                {COLUMNS.map((column) => (
                  <col key={column.key} style={{ width: column.width }} />
                ))}
              </colgroup>
              <thead className="sticky top-0 z-10 bg-card">
                <tr className="h-[30px] border-b border-border/70">
                  <th scope="col" className="px-1 pl-3.5">
                    <Checkbox
                      className="h-3.5 w-3.5"
                      aria-label="Seleccionar todas las filas de la página"
                      checked={allPageSelected}
                      onCheckedChange={toggleAllPage}
                    />
                  </th>
                  <th scope="col" aria-label="Novedad" />
                  <th scope="col" aria-label="Favorito" />
                  {COLUMNS.slice(3).map((column) => {
                    const active = sorting[0]?.id === column.key;
                    const direction = active ? (sorting[0].desc ? "descending" : "ascending") : "none";
                    return (
                      <th
                        key={column.key}
                        scope="col"
                        aria-sort={direction}
                        className={cn(
                          "px-1 font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground",
                          column.align === "right" ? "text-right" : "text-left",
                          column.key === "tecnologia" && "pr-3.5",
                        )}
                      >
                        <button
                          type="button"
                          onClick={() => toggleSort(column.key)}
                          className={cn(
                            "inline-flex items-center gap-1 rounded px-1 py-0.5 transition-colors duration-140 ease-out hover:text-foreground",
                            active && "text-primary",
                          )}
                        >
                          {column.label}
                          {active ? (
                            sorting[0].desc ? (
                              <ArrowDown className="h-3 w-3" aria-hidden="true" />
                            ) : (
                              <ArrowUp className="h-3 w-3" aria-hidden="true" />
                            )
                          ) : (
                            <ArrowUpDown className="h-3 w-3 opacity-30" aria-hidden="true" />
                          )}
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>

              <tbody>
                {isLoading ? (
                  Array.from({ length: 12 }, (_, index) => (
                    <tr key={index} className="border-b border-border/30">
                      <td colSpan={COLUMNS.length} className="px-3.5 py-1.5">
                        <Skeleton className="h-6 w-full rounded" />
                      </td>
                    </tr>
                  ))
                ) : error || isEmpty ? null : (
                  mergedRows.map((row, index) => {
                    const open = detailId === row.id_externo;
                    const picked = Boolean(rowSelection[row.id_externo]);
                    const isCursor = index === Math.min(cursor, mergedRows.length - 1);
                    const favorite = watchedIds.has(row.id_externo);
                    const ccaaOn = row.ccaa ? ccaas.includes(row.ccaa) : false;
                    const tecOn = row.tecnologia ? tecnologias.includes(row.tecnologia) : false;

                    return (
                      <tr
                        key={row.id_externo}
                        data-detalle-row={isCursor ? "cursor" : undefined}
                        tabIndex={0}
                        aria-selected={picked}
                        onClick={() => {
                          setCursor(index);
                          openDetail(row.id_externo);
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            setCursor(index);
                            openDetail(row.id_externo);
                          }
                        }}
                        style={{ height: rowHeight }}
                        className={cn(
                          "relative cursor-pointer border-b border-border/30 transition-colors duration-110 ease-out",
                          isFetching && "opacity-60",
                          open
                            ? "bg-primary/9"
                            : picked
                              ? "bg-primary/4"
                              : "hover:bg-primary/5",
                          isCursor && !open && "ring-1 ring-inset ring-primary/25",
                        )}
                      >
                        <td className="relative px-1 pl-3.5">
                          <span
                            aria-hidden="true"
                            className="absolute inset-y-0 left-0 w-0.5 transition-colors duration-110 ease-out"
                            style={{ background: open ? bandColor(row.band) : "transparent" }}
                          />
                          <Checkbox
                            className="h-3.5 w-3.5"
                            aria-label={`Seleccionar ${row.titulo}`}
                            checked={picked}
                            onCheckedChange={() => toggleRow(row.id_externo)}
                            onClick={(event) => event.stopPropagation()}
                          />
                        </td>
                        <td>
                          {row.isNew && (
                            <span
                              className="block h-1.5 w-1.5 rounded-full bg-[hsl(var(--info))]"
                              title="Publicada desde tu última visita"
                            />
                          )}
                        </td>
                        <td>
                          <button
                            type="button"
                            aria-label={favorite ? "Quitar de favoritos" : "Añadir a favoritos"}
                            aria-pressed={favorite}
                            title="Seguir · S"
                            onClick={(event) => {
                              event.stopPropagation();
                              toggleFavorite(row.id_externo);
                            }}
                            className="tf-pressable grid h-5 w-5 place-items-center rounded"
                          >
                            <Star
                              className={cn(
                                "h-3.5 w-3.5 transition-colors duration-140 ease-out",
                                favorite ? "fill-primary text-primary" : "text-muted-foreground/45",
                              )}
                            />
                          </button>
                        </td>
                        <td className="truncate px-1 font-mono text-[10.5px] text-muted-foreground">
                          {row.id_externo.replace("PLACSP-", "")}
                        </td>
                        <td className="px-1">
                          <span
                            title={row.titulo}
                            className={cn(
                              "block truncate text-[12.5px] leading-[1.3] tracking-[-0.005em]",
                              open ? "font-semibold text-foreground" : "font-medium",
                            )}
                          >
                            {row.titulo}
                          </span>
                        </td>
                        <td className="px-1">
                          <span
                            title={row.organo_contratacion ?? ""}
                            className="block truncate text-xs leading-[1.3] text-muted-foreground"
                          >
                            {truncate(row.organo_contratacion, compact ? 30 : 40)}
                          </span>
                        </td>
                        <td className="tf-tnum px-1 text-right font-mono text-xs font-semibold">
                          {compact ? shortEur(row.importe) : formatCurrency(row.importe)}
                        </td>
                        <td className="px-1">
                          <StatusBadge value={row.estado} kind="estado" className="text-[10.5px]" />
                        </td>
                        <td className="truncate px-1 align-middle whitespace-nowrap">
                          <span
                            className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle"
                            style={{ background: bandColor(row.band) }}
                            aria-hidden="true"
                          />
                          <span className="tf-tnum mr-1.5 font-mono text-xs font-semibold">
                            {row.score != null ? Math.round(row.score) : "—"}
                          </span>
                          <span className="font-mono text-[9.5px] text-muted-foreground">
                            {row.band ?? ""}
                          </span>
                        </td>
                        <td className="tf-tnum px-1 text-right font-mono text-[10.5px] text-muted-foreground">
                          {formatDate(row.fecha_publicacion)}
                        </td>
                        <td className="px-1">
                          {row.ccaa ? (
                            <button
                              type="button"
                              title={`Filtrar por ${row.ccaa}`}
                              onClick={(event) => {
                                event.stopPropagation();
                                toggleCcaa(row.ccaa!);
                              }}
                              className={cn(
                                "block max-w-full truncate rounded px-1.5 py-0.5 text-left text-[11.5px] transition-colors duration-140 ease-out",
                                ccaaOn
                                  ? "border border-primary/40 bg-primary/14 font-semibold text-primary"
                                  : "border border-transparent text-muted-foreground hover:text-foreground",
                              )}
                            >
                              {row.ccaa}
                            </button>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="truncate px-1 font-mono text-[10.5px] text-muted-foreground">
                          {row.cpv ?? "—"}
                        </td>
                        <td className="px-1 pr-3.5">
                          {row.tecnologia ? (
                            <button
                              type="button"
                              title={`Filtrar por ${row.tecnologia}`}
                              onClick={(event) => {
                                event.stopPropagation();
                                toggleTecnologia(row.tecnologia!);
                              }}
                              className={cn(
                                "block max-w-full truncate rounded border px-1.5 py-0.5 text-left text-[10.5px] font-medium transition-colors duration-140 ease-out",
                                tecOn
                                  ? "border-[hsl(var(--info)/0.5)] bg-[hsl(var(--info)/0.2)] text-[hsl(var(--info))]"
                                  : "border-[hsl(var(--info)/0.22)] bg-[hsl(var(--info)/0.08)] text-[hsl(var(--info))]",
                              )}
                            >
                              {row.tecnologia}
                            </button>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>

            {/* Los tres estados viven fuera de la `<table>`: una alerta dentro
                de una celda se anuncia como dato de la tabla, que es lo que no
                es. La cabecera de columnas se queda visible en los tres. */}
            {error && (
              <div
                role="alert"
                className="mx-auto my-10 max-w-[560px] rounded-xl border border-destructive/40 bg-destructive/8 px-6 py-5"
              >
                <div className="mb-2 flex items-center gap-2.5">
                  <span className="grid h-5.5 w-5.5 flex-none place-items-center rounded-full border border-destructive/50 text-[12px] font-semibold text-destructive">
                    !
                  </span>
                  <span className="text-[13.5px] font-semibold text-destructive">
                    Error al cargar la tabla
                  </span>
                </div>
                <p className="mb-3.5 font-mono text-xs leading-[1.55] text-destructive/80">
                  {(error as Error).message}
                </p>
                <button
                  type="button"
                  onClick={() => void refetch()}
                  className="tf-pressable h-[30px] rounded-md border border-border/80 px-3 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
                >
                  ↻ Reintentar
                </button>
              </div>
            )}

            {isEmpty && (
              <div className="px-5 py-[90px] text-center">
                <div className="mb-1.5 font-display text-[15px] font-semibold leading-[1.3]">
                  Sin resultados
                </div>
                <p className="mb-3.5 text-[13px] leading-[1.5] text-muted-foreground">
                  Ninguna licitación encaja con el ámbito actual.
                </p>
                <button
                  type="button"
                  onClick={resetFilters}
                  className="tf-pressable h-[30px] rounded-md border border-primary/40 bg-primary/12 px-3 text-xs font-medium text-primary"
                >
                  Limpiar ámbito
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Pie: contador, atajos y paginación */}
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
            <button
              type="button"
              title="Primera página"
              aria-label="Primera página"
              className={pageButton}
              onClick={() => table.setPageIndex(0)}
              disabled={!table.getCanPreviousPage()}
            >
              <ChevronsLeft className="h-3 w-3" aria-hidden="true" />
            </button>
            <button
              type="button"
              title="Anterior"
              aria-label="Página anterior"
              className={pageButton}
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              <ChevronLeft className="h-3 w-3" aria-hidden="true" />
            </button>
            {pageWindow.map((page) => (
              <button
                key={page}
                type="button"
                aria-current={page === pagination.pageIndex ? "page" : undefined}
                onClick={() => table.setPageIndex(page)}
                className={cn(
                  "tf-tnum tf-pressable h-6.5 min-w-6.5 rounded-md border px-1 font-mono text-[11px] transition-colors duration-140 ease-out",
                  page === pagination.pageIndex
                    ? "border-primary/40 bg-primary/14 text-primary"
                    : "border-border/70 text-muted-foreground hover:text-foreground",
                )}
              >
                {page + 1}
              </button>
            ))}
            <button
              type="button"
              title="Siguiente"
              aria-label="Página siguiente"
              className={pageButton}
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              <ChevronRight className="h-3 w-3" aria-hidden="true" />
            </button>
            <button
              type="button"
              title="Última página"
              aria-label="Última página"
              className={pageButton}
              onClick={() => table.setPageIndex(totalPages - 1)}
              disabled={!table.getCanNextPage()}
            >
              <ChevronsRight className="h-3 w-3" aria-hidden="true" />
            </button>
          </nav>
        </div>
      </section>

      {detailId && detailWithScore && (
        // El inspector escala con la pantalla en vez de quedarse en 428px fijos.
        // Con ese ancho la ficha era la parte estrecha del plano: el título
        // rompía en tres líneas, los diez campos vivían en dos columnas de 200px
        // y el chat de IA leía como una columna de móvil. El suelo de 28rem
        // mantiene el panel usable en un portátil de 1280 y el techo de 42rem
        // evita que en un monitor de 2560 la ficha se estire sin ganar nada.
        <div className="hidden w-[clamp(28rem,32vw,42rem)] flex-none xl:flex">
          <DetailInspector licitacion={detailWithScore} onClose={closeDetail} />
        </div>
      )}

      {/* Barra flotante de selección */}
      {selectedIds.length > 0 && (
        <div className="pointer-events-none fixed inset-x-0 bottom-[68px] z-40 flex justify-center">
          <div className="tf-glass-strong pointer-events-auto flex items-center gap-2 rounded-xl border border-border/70 px-3.5 py-2.5 shadow-xl animate-in fade-in-0 slide-in-from-bottom-2 duration-[260ms]">
            <span className="tf-tnum text-[12.5px] font-semibold">
              {selectedIds.length} seleccionadas
            </span>
            <span className="h-4.5 w-px bg-border/70" aria-hidden="true" />
            <Button
              variant="outline"
              size="sm"
              className="h-7 px-2.5 text-xs"
              onClick={() => setShowComparator(true)}
              disabled={selectedIds.length < 2 || selectedIds.length > 3}
              title="Comparar 2 o 3 licitaciones"
            >
              <GitCompareArrows className="h-3.5 w-3.5" />
              Comparar ({selectedIds.length})
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 px-2.5 text-xs"
              onClick={() =>
                downloadCsv(selectedItems, `seleccion_${new Date().toISOString().slice(0, 10)}.csv`)
              }
            >
              <Download className="h-3.5 w-3.5" />
              Exportar selección
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 px-2.5 text-xs"
              onClick={() => {
                selectedIds.forEach((id) => addWatchlistItem.mutate(id));
                setRowSelection({});
              }}
            >
              <Star className="h-3.5 w-3.5" />
              Seguir
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 px-0"
              aria-label="Limpiar selección"
              onClick={() => setRowSelection({})}
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}

      {showComparator && selectedItems.length >= 2 && (
        <Comparator
          items={selectedItems.map((row) => ({
            id_externo: row.id_externo,
            titulo: row.titulo,
            organo_contratacion: row.organo_contratacion ?? null,
            importe: row.importe ?? null,
            estado: row.estado ?? null,
            fecha_publicacion: row.fecha_publicacion ?? null,
            ccaa: row.ccaa ?? null,
            cpv: row.cpv ?? null,
            url: row.url ?? null,
            // El listado no trae `fuente` (solo la ficha), y el comparador no
            // pinta el enlace externo: mismo `null` que el resto de campos que
            // esta proyección no puede rellenar.
            fuente: null,
            tecnologia: row.tecnologia ?? null,
            tipo_contrato: null,
            provincia: null,
            fecha_limite: null,
            fecha_inicio: null,
            fecha_fin: null,
            descripcion: null,
            score: row.score,
          }))}
          onClose={() => startTransition(() => setShowComparator(false))}
        />
      )}
    </div>
  );
}
