"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { IndicadorOrden } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { cn, formatCurrency, formatDate, formatNumber } from "@/lib/utils";
import type { TimelineScatterResult } from "@/lib/api-types";
import { ITEMS_PER_PAGE, TIMELINE_MAX, esNueva, type TimelineItem } from "./types";
import { useNovedades } from "../_hooks/use-novedades";
import { PublicacionesPanel } from "./publicaciones-panel";

/**
 * Publicaciones del periodo: el panel de cortes y la tabla que lo desglosa.
 *
 * El gráfico vive en `publicaciones-panel.tsx` — allí está el porqué de sus
 * tres cortes y de que la nube de puntos haya dejado de ser el corte por
 * defecto. Aquí queda la tabla: siete columnas ordenables, paginación de diez
 * y el tope del endpoint declarado, porque «1–10 de 1.000» se leía como el
 * total del ámbito cuando es el techo de `/resumen/timeline`.
 *
 * **Las filas nuevas** (después de tu última visita) llevan el punto de
 * `esNueva`, con su leyenda en la cabecera cuando hay alguna. El recuento es la
 * tarjeta «Nuevas» de «Mercado abierto», mismo corte y mismo ámbito
 * (`_hooks/use-novedades.ts`).
 */

/**
 * Anchos como clases y no como `style`: cada estilo en línea ata `style-src` a
 * `'unsafe-inline'` (scripts/check_inline_styles.py). Cadenas literales, para
 * que el JIT de Tailwind las vea.
 */
const COLUMNS: {
  key: keyof TimelineItem;
  label: string;
  ancho?: string;
  align?: "right";
}[] = [
  { key: "titulo", label: "Título" },
  { key: "organo_contratacion", label: "Órgano", ancho: "w-[160px]" },
  { key: "ccaa", label: "CCAA", ancho: "w-[104px]" },
  { key: "tipo_contrato", label: "Tipo", ancho: "w-[104px]" },
  { key: "importe", label: "Importe", ancho: "w-[108px]", align: "right" },
  { key: "fecha_publicacion", label: "Fecha", ancho: "w-[84px]" },
  { key: "estado", label: "Estado", ancho: "w-[112px]" },
];

export function TimelineSection() {
  const { rango } = useFilters();
  const novedades = useNovedades();
  const corteNovedades = novedades.data?.desde ?? null;

  const [pubPage, setPubPage] = useState(0);
  const [pubSortKey, setPubSortKey] = useState<keyof TimelineItem>("fecha_publicacion");
  const [pubSortDir, setPubSortDir] = useState<"asc" | "desc">("desc");

  // Ventana por defecto de 30 días cuando el ámbito no fija fecha de inicio.
  // eslint-disable-next-line react-hooks/purity
  const desde = rango.desde ?? new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
  const timeline = useFilteredQuery<TimelineScatterResult>(
    ["analytics", "resumen", "timeline", desde],
    "/api/v1/analytics/resumen/timeline",
    // El fallo lo pinta el panel: sin toast encima.
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
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

  const hayNuevas = useMemo(
    () => items.some((item) => esNueva(item.fecha_publicacion, corteNovedades)),
    [items, corteNovedades],
  );

  const totalPubPages = Math.max(1, Math.ceil(sortedPubs.length / ITEMS_PER_PAGE));
  const pagedPubs = sortedPubs.slice(pubPage * ITEMS_PER_PAGE, (pubPage + 1) * ITEMS_PER_PAGE);

  return (
    <div className="mb-5.5 flex flex-col gap-3.5">
      <PublicacionesPanel />

      <Panel>
        <PanelTitle
          title="Últimas publicaciones"
          hint={
            hayNuevas ? (
              <span className="inline-flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 flex-none rounded-full bg-primary" aria-hidden="true" />
                nuevas desde tu última visita
              </span>
            ) : undefined
          }
          actions={
            <span className="tf-tnum text-tf-micro text-muted-foreground">
              {sortedPubs.length === 0
                ? "—"
                : `${pubPage * ITEMS_PER_PAGE + 1}–${Math.min(
                    (pubPage + 1) * ITEMS_PER_PAGE,
                    sortedPubs.length,
                  )} de ${formatNumber(sortedPubs.length)}${topeAlcanzado ? " más recientes" : ""}`}
            </span>
          }
        />

        {timeline.error && (
          <PanelError
            variant="inline"
            title="No se pudo cargar el listado"
            error={timeline.error}
            onRetry={() => void timeline.refetch()}
          />
        )}

        {topeAlcanzado && (
          <p className="mb-2 text-tf-micro text-muted-foreground">
            El orden se aplica a las {formatNumber(TIMELINE_MAX)} publicaciones más recientes del
            ámbito, no a todas: para verlas todas,{" "}
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
                  <col key={column.key} className={column.ancho} />
                ))}
              </colgroup>
              <thead>
                <tr className="border-b border-border/70">
                  {COLUMNS.map((column) => {
                    const active = pubSortKey === column.key;
                    return (
                      <th
                        key={column.key}
                        scope="col"
                        aria-sort={
                          active ? (pubSortDir === "asc" ? "ascending" : "descending") : "none"
                        }
                        className={cn("pb-2", column.align === "right" ? "text-right" : "text-left")}
                      >
                        {/* Ordenable: la receta de cabecera va en el botón, y el
                            `group` enciende la doble flecha al pasar o enfocar. */}
                        <button
                          type="button"
                          onClick={() => togglePubSort(column.key)}
                          className={cn(
                            CABECERA_COLUMNA,
                            "group inline-flex items-center gap-1 rounded-sm px-1 py-0.5 transition-colors hover:text-foreground",
                            active && "text-foreground",
                          )}
                        >
                          {column.label}
                          <IndicadorOrden direccion={active ? pubSortDir : false} />
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
                          <Skeleton className="h-5 w-full rounded-sm" />
                        </td>
                      </tr>
                    ))
                  : pagedPubs.map((item) => (
                      <tr key={item.id_externo} className="border-b border-border/25">
                        <td className="px-1 py-1.5">
                          <Link
                            href={`/detalle?lic=${encodeURIComponent(item.id_externo)}`}
                            className="flex min-w-0 items-center gap-2 text-tf-meta font-medium hover:underline"
                          >
                            {esNueva(item.fecha_publicacion, corteNovedades) && (
                              <>
                                <span
                                  className="h-1.5 w-1.5 flex-none rounded-full bg-primary"
                                  aria-hidden="true"
                                />
                                <span className="sr-only">Nueva desde tu última visita.</span>
                              </>
                            )}
                            <span className="min-w-0 truncate">{item.titulo}</span>
                          </Link>
                        </td>
                        <td className="truncate px-1 text-tf-micro text-muted-foreground">
                          {item.organo_contratacion ?? "—"}
                        </td>
                        <td className="truncate px-1 text-tf-micro text-muted-foreground">
                          {item.ccaa ?? "—"}
                        </td>
                        <td className="truncate px-1 text-tf-micro text-muted-foreground">
                          {item.tipo_contrato ?? "—"}
                        </td>
                        <td className="tf-tnum whitespace-nowrap px-1 text-right text-tf-micro font-semibold">
                          {formatCurrency(item.importe)}
                        </td>
                        <td className="tf-tnum whitespace-nowrap px-1 text-tf-micro text-muted-foreground">
                          {formatDate(item.fecha_publicacion)}
                        </td>
                        <td className="px-1">
                          <StatusBadge value={item.estado} kind="estado" className="h-5 px-1.5 text-tf-micro" />
                        </td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
        )}

        {!timeline.error && !timeline.isLoading && pagedPubs.length === 0 && (
          <PanelEmpty
            title="Sin publicaciones en la ventana"
            hint="Amplía las fechas del ámbito para ver más."
          />
        )}

        {sortedPubs.length > ITEMS_PER_PAGE && (
          <nav
            aria-label="Paginación de publicaciones"
            className="mt-2.5 flex items-center gap-2 border-t border-border/40 pt-2.5"
          >
            <div className="flex-1" />
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              aria-label="Página anterior"
              disabled={pubPage === 0}
              onClick={() => setPubPage((page) => Math.max(0, page - 1))}
            >
              <ChevronLeft aria-hidden="true" />
            </Button>
            <span className="tf-tnum text-tf-micro text-muted-foreground">
              {pubPage + 1} / {totalPubPages}
            </span>
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              aria-label="Página siguiente"
              disabled={pubPage >= totalPubPages - 1}
              onClick={() => setPubPage((page) => Math.min(totalPubPages - 1, page + 1))}
            >
              <ChevronRight aria-hidden="true" />
            </Button>
          </nav>
        )}
      </Panel>
    </div>
  );
}
