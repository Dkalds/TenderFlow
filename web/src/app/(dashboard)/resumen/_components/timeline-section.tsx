"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowUpDown, ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "lucide-react";
import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import { cn, formatCurrency, formatDate, formatNumber } from "@/lib/utils";
import type { TimelineScatterResult } from "@/lib/api-types";
import { ITEMS_PER_PAGE, TIMELINE_MAX, type TimelineItem } from "./types";
import { PublicacionesPanel } from "./publicaciones-panel";

/**
 * Publicaciones del periodo: el panel de cortes y la tabla que lo desglosa.
 *
 * El gráfico vive en `publicaciones-panel.tsx` — allí está el porqué de sus
 * tres cortes y de que la nube de puntos haya dejado de ser el corte por
 * defecto. Aquí queda la tabla: siete columnas ordenables, paginación de diez
 * y el tope del endpoint declarado, porque «1–10 de 1.000» se leía como el
 * total del ámbito cuando es el techo de `/resumen/timeline`.
 */

const COLUMNS: {
  key: keyof TimelineItem;
  label: string;
  width: string;
  align?: "right";
}[] = [
  { key: "titulo", label: "Título", width: "auto" },
  { key: "organo_contratacion", label: "Órgano", width: "160px" },
  { key: "ccaa", label: "CCAA", width: "104px" },
  { key: "tipo_contrato", label: "Tipo", width: "104px" },
  { key: "importe", label: "Importe", width: "108px", align: "right" },
  { key: "fecha_publicacion", label: "Fecha", width: "84px" },
  { key: "estado", label: "Estado", width: "112px" },
];

export function TimelineSection() {
  const { rango } = useFilters();

  const [pubPage, setPubPage] = useState(0);
  const [pubSortKey, setPubSortKey] = useState<keyof TimelineItem>("fecha_publicacion");
  const [pubSortDir, setPubSortDir] = useState<"asc" | "desc">("desc");

  // Ventana por defecto de 30 días cuando el ámbito no fija fecha de inicio.
  // eslint-disable-next-line react-hooks/purity
  const desde = rango.desde ?? new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
  const timeline = useFilteredQuery<TimelineScatterResult>(
    ["analytics", "resumen", "timeline", desde],
    "/api/v1/analytics/resumen/timeline",
    { staleTime: 5 * 60 * 1000 },
    { fecha_desde: desde },
  );

  const items = useMemo(
    () => (timeline.data?.items ?? []) as TimelineItem[],
    [timeline.data?.items],
  );
  const topeAlcanzado = items.length >= TIMELINE_MAX;

  const sortedPubs = useMemo(() => {
    const copia = [...items];
    copia.sort((a, b) => {
      const left = a[pubSortKey];
      const right = b[pubSortKey];
      if (left == null && right == null) return 0;
      if (left == null) return 1;
      if (right == null) return -1;
      if (typeof left === "number" && typeof right === "number") {
        return pubSortDir === "asc" ? left - right : right - left;
      }
      const compared = String(left).localeCompare(String(right), "es", { sensitivity: "base" });
      return pubSortDir === "asc" ? compared : -compared;
    });
    return copia;
  }, [items, pubSortKey, pubSortDir]);

  // Ordenar por otra columna vuelve a la primera página: «página 3 de otro
  // criterio» no señala las mismas filas.
  const togglePubSort = (key: keyof TimelineItem) => {
    if (pubSortKey === key) {
      setPubSortDir((direction) => (direction === "asc" ? "desc" : "asc"));
    } else {
      setPubSortKey(key);
      setPubSortDir("asc");
    }
    setPubPage(0);
  };

  const totalPubPages = Math.max(1, Math.ceil(sortedPubs.length / ITEMS_PER_PAGE));
  const pagedPubs = sortedPubs.slice(pubPage * ITEMS_PER_PAGE, (pubPage + 1) * ITEMS_PER_PAGE);

  const pageButton =
    "tf-pressable grid h-6 w-6 place-items-center rounded-md border border-border/70 text-muted-foreground transition-colors duration-140 ease-out hover:text-foreground disabled:cursor-default disabled:opacity-35";

  return (
    <div className="mb-5.5 flex flex-col gap-3.5">
      <PublicacionesPanel />

      <Panel>
        <PanelTitle
          title="Últimas publicaciones"
          hint="ordena por cualquier columna"
          actions={
            <span className="tf-tnum text-muted-foreground font-mono text-[10.5px]">
              {sortedPubs.length === 0
                ? "—"
                : `${pubPage * ITEMS_PER_PAGE + 1}–${Math.min(
                    (pubPage + 1) * ITEMS_PER_PAGE,
                    sortedPubs.length,
                  )} de ${sortedPubs.length}${topeAlcanzado ? " (tope)" : ""}`}
            </span>
          }
        />

        {timeline.error && (
          <PanelError
            title="No se pudo cargar el listado"
            detail={(timeline.error as Error).message}
            onRetry={() => void timeline.refetch()}
          />
        )}

        {topeAlcanzado && (
          <p className="text-muted-foreground mb-2 text-[10.5px] leading-[1.45]">
            El orden se aplica sobre las {formatNumber(TIMELINE_MAX)} publicaciones más
            recientes del ámbito, no sobre el total: para recorrer el corpus entero,{" "}
            <Link href="/detalle" className="text-primary hover:underline">
              abre el listado completo
            </Link>
            .
          </p>
        )}

        {!timeline.error && (
        <div className="overflow-x-auto">
          <table className="w-full table-fixed border-collapse">
            <colgroup>
              {COLUMNS.map((column) => (
                <col key={column.key} style={{ width: column.width }} />
              ))}
            </colgroup>
            <thead>
              <tr className="border-border/70 border-b">
                {COLUMNS.map((column) => {
                  const active = pubSortKey === column.key;
                  return (
                    <th
                      key={column.key}
                      scope="col"
                      aria-sort={
                        active ? (pubSortDir === "asc" ? "ascending" : "descending") : "none"
                      }
                      className={cn(
                        "text-muted-foreground pb-2 font-mono text-[9px] font-semibold tracking-[0.1em] uppercase",
                        column.align === "right" ? "text-right" : "text-left",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => togglePubSort(column.key)}
                        className={cn(
                          "hover:text-foreground inline-flex items-center gap-1 rounded px-1 py-0.5 transition-colors duration-140 ease-out",
                          active && "text-primary",
                        )}
                      >
                        {column.label}
                        {active ? (
                          pubSortDir === "asc" ? (
                            <ChevronUp className="h-3 w-3" aria-hidden="true" />
                          ) : (
                            <ChevronDown className="h-3 w-3" aria-hidden="true" />
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
              {timeline.isLoading
                ? Array.from({ length: 6 }, (_, index) => (
                    <tr key={index}>
                      <td colSpan={COLUMNS.length} className="py-1.5">
                        <Skeleton className="h-5 w-full rounded" />
                      </td>
                    </tr>
                  ))
                : pagedPubs.map((item) => (
                    <tr key={item.id_externo} className="border-border/25 border-b">
                      <td className="px-1 py-1.5">
                        <Link
                          href={`/detalle?lic=${encodeURIComponent(item.id_externo)}`}
                          className="block truncate text-[11.5px] leading-[1.4] font-medium hover:underline"
                        >
                          {item.titulo}
                        </Link>
                      </td>
                      <td className="text-muted-foreground truncate px-1 text-[11px]">
                        {item.organo_contratacion ?? "—"}
                      </td>
                      <td className="text-muted-foreground truncate px-1 text-[11px]">
                        {item.ccaa ?? "—"}
                      </td>
                      <td className="text-muted-foreground truncate px-1 text-[11px]">
                        {item.tipo_contrato ?? "—"}
                      </td>
                      <td className="tf-tnum px-1 text-right font-mono text-[11px] font-semibold whitespace-nowrap">
                        {formatCurrency(item.importe)}
                      </td>
                      <td className="text-muted-foreground px-1 font-mono text-[10.5px] whitespace-nowrap">
                        {formatDate(item.fecha_publicacion)}
                      </td>
                      <td className="px-1">
                        <StatusBadge value={item.estado} kind="estado" className="text-[10.5px]" />
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
        )}

        {!timeline.error && !timeline.isLoading && pagedPubs.length === 0 && (
          <PanelEmpty message="Sin publicaciones que mostrar." />
        )}

        {sortedPubs.length > ITEMS_PER_PAGE && (
          <nav
            aria-label="Paginación de publicaciones"
            className="border-border/40 mt-2.5 flex items-center gap-2 border-t pt-2.5"
          >
            <div className="flex-1" />
            <button
              type="button"
              aria-label="Página anterior"
              className={pageButton}
              disabled={pubPage === 0}
              onClick={() => setPubPage((page) => Math.max(0, page - 1))}
            >
              <ChevronLeft className="h-3 w-3" aria-hidden="true" />
            </button>
            <span className="tf-tnum text-muted-foreground font-mono text-[10.5px]">
              {pubPage + 1} / {totalPubPages}
            </span>
            <button
              type="button"
              aria-label="Página siguiente"
              className={pageButton}
              disabled={pubPage >= totalPubPages - 1}
              onClick={() => setPubPage((page) => Math.min(totalPubPages - 1, page + 1))}
            >
              <ChevronRight className="h-3 w-3" aria-hidden="true" />
            </button>
          </nav>
        )}
      </Panel>
    </div>
  );
}
