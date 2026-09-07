"use client";

import { startTransition, useCallback, useMemo, useState } from "react";
import { parseAsString, useQueryState } from "nuqs";
import { useReactTable, getCoreRowModel } from "@tanstack/react-table";
import { Comparator } from "@/components/comparator";
import { formatNumber } from "@/lib/utils";
import { useDensity } from "@/lib/density";
import { descargarBlob } from "@/lib/export";
import { useFilterParams, useFilters } from "@/lib/filters";
import { toggleValue } from "@/lib/chart-interaction";
import type { LicitacionSummary } from "@/lib/api-types";
import { useModoInspector } from "../radar/_hooks/use-media-query";
import { DetalleBarra } from "./_components/detalle-barra";
import { COLUMNS } from "./_components/detalle-columnas";
import { DetalleInspectorPanel } from "./_components/detalle-inspector-panel";
import { DetallePie } from "./_components/detalle-pie";
import { DetalleSeleccion } from "./_components/detalle-seleccion";
import { DetalleTabla } from "./_components/detalle-tabla";
import { buildCsv } from "./_hooks/detalle-table-model";
import { useCierreRecorte } from "./_hooks/use-cierre-recorte";
import { useDetalleFavoritos } from "./_hooks/use-detalle-favoritos";
import { useDetalleQueries, useDetailWithScore } from "./_hooks/use-detalle-queries";
import { useDetalleRows, useDetalleTableState } from "./_hooks/use-detalle-table";
import { useDetalleTeclado } from "./_hooks/use-detalle-teclado";

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
 *
 * Esta pantalla es la composición: el estado y las consultas viven en
 * `_hooks/`, cada bloque de UI en `_components/`.
 */

function downloadCsv(rows: LicitacionSummary[], filename: string) {
  // Vía `descargarBlob` y no con un ancla propia: esta exportación se arma en el
  // cliente, no pasa por `/exports/download` y por eso no emitía ningún evento.
  descargarBlob(filename, new Blob([buildCsv(rows)], { type: "text/csv" }), "detalle");
}

export default function DetallePage() {
  const filterParams = useFilterParams();
  const { q, ccaas, setCcaas, tecnologias, setTecnologias, resetFilters } = useFilters();
  const toggleCcaa = useCallback(
    (ccaa: string) => setCcaas(toggleValue(ccaa, ccaas)),
    [ccaas, setCcaas],
  );
  const toggleTecnologia = useCallback(
    (tec: string) => setTecnologias(toggleValue(tec, tecnologias)),
    [tecnologias, setTecnologias],
  );

  // Recorte propio de la pantalla (`?cierre_desde=`/`?cierre_hasta=`), que se
  // suma al ámbito global en vez de sustituirlo: el deep-link de una tarjeta de
  // /resumen llega con la ventana de cierre y con los chips de ámbito que el
  // usuario tuviera puestos, y la tabla tiene que respetar los dos.
  const cierre = useCierreRecorte();
  const queryFilters = useMemo(
    () => ({ ...filterParams, ...cierre.params }),
    [filterParams, cierre.params],
  );

  const tabla = useDetalleTableState({ filterParams: queryFilters, q });
  const { sorting, setSorting, pagination, setPagination, rowSelection, setRowSelection } = tabla;

  // Permalink de la ficha: ?lic=<id_externo>, con push al historial (atrás
  // cierra el inspector) y URL compartible desde cualquier fila.
  const [detailId, setDetailId] = useQueryState(
    "lic",
    parseAsString.withOptions({ history: "push", shallow: true }),
  );
  const [showComparator, setShowComparator] = useState(false);
  const closeComparator = useCallback(() => setShowComparator(false), []);
  const { compact, toggleCompact } = useDensity();
  const modo = useModoInspector();
  const favoritos = useDetalleFavoritos();

  const queries = useDetalleQueries({ queryParams: tabla.queryParams, detailId });

  // Orden en cliente sólo para las columnas que el backend no sabe ordenar
  // (`clientSorted`): es un orden sobre la página cargada, no sobre el total, y
  // el pie de la tabla lo dice.
  const filas = useDetalleRows({
    items: queries.data?.items,
    total: queries.data?.total,
    scoring: queries.scoring,
    lastViewed: favoritos.lastViewed,
    activeSort: tabla.activeSort,
    pagination,
    rowSelection,
    setRowSelection,
  });
  const { mergedRows, totalPages, selectedIds, selectedItems } = filas;

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

  const openDetail = useCallback((id: string) => void setDetailId(id), [setDetailId]);

  const closeDetail = useCallback(() => {
    // startTransition: cerrar desmonta bloques pesados (IA, documentos,
    // eventos); diferirlo evita bloquear el hilo principal en el propio clic.
    startTransition(() => {
      void setDetailId(null, { history: "replace" });
    });
  }, [setDetailId]);

  const { cursor, setCursor } = useDetalleTeclado({
    mergedRows,
    detailId,
    showComparator,
    closeComparator,
    closeDetail,
    openDetail,
    toggleFavorite: favoritos.toggleFavorite,
  });

  const detailWithScore = useDetailWithScore(queries.detailData, filas.scoreMap);
  const isEmpty = !queries.isLoading && !queries.error && mergedRows.length === 0;

  const sortLabel = sorting.length
    ? `${COLUMNS.find((column) => column.key === sorting[0].id)?.label ?? sorting[0].id} ${
        sorting[0].desc ? "↓" : "↑"
      }`
    : null;

  const showingLine = queries.data
    ? `Mostrando ${pagination.pageIndex * pagination.pageSize + 1}–${Math.min(
        (pagination.pageIndex + 1) * pagination.pageSize,
        queries.data.total,
      )} de ${formatNumber(queries.data.total)}`
    : "—";

  return (
    <div className="flex h-[calc(100vh-52px)] min-h-0">
      <section className="flex min-w-0 flex-1 flex-col border-r border-border/70">
        <DetalleBarra
          cierreLabel={cierre.label}
          onClearCierre={() => {
            cierre.clear();
            // Volver a la primera página: «página 7» de un recorte que ya no
            // existe apunta a un tramo distinto del listado ensanchado.
            setPagination((current) => ({ ...current, pageIndex: 0 }));
          }}
          sortLabel={sortLabel}
          onClearSort={() => setSorting([])}
          compact={compact}
          onCompactChange={(next) => {
            if (compact !== next) toggleCompact();
          }}
        />

        <DetalleTabla
          rows={mergedRows}
          sorting={sorting}
          allPageSelected={filas.allPageSelected}
          onToggleAllPage={filas.toggleAllPage}
          onToggleSort={tabla.toggleSort}
          isLoading={queries.isLoading}
          isFetching={queries.isFetching}
          error={queries.error}
          onRetry={() => void queries.refetch()}
          vacia={isEmpty}
          conRecorte={Boolean(cierre.label)}
          onLimpiar={() => {
            resetFilters();
            // El recorte por cierre también: si sólo se limpiara el ámbito, el
            // botón dejaría la pantalla igual de vacía y sin nada más que pulsar.
            cierre.clear();
          }}
          detailId={detailId}
          cursor={cursor}
          rowSelection={rowSelection}
          watchedIds={favoritos.watchedIds}
          ccaas={ccaas}
          tecnologias={tecnologias}
          compact={compact}
          rowHeight={compact ? 34 : 44}
          onOpen={(index, id) => {
            setCursor(index);
            openDetail(id);
          }}
          onToggleSelect={tabla.toggleRow}
          onToggleFavorite={favoritos.toggleFavorite}
          onToggleCcaa={toggleCcaa}
          onToggleTecnologia={toggleTecnologia}
        />

        <DetallePie
          showingLine={showingLine}
          clientSorted={tabla.clientSorted}
          pageIndex={pagination.pageIndex}
          totalPages={totalPages}
          pageWindow={filas.pageWindow}
          canPrevious={table.getCanPreviousPage()}
          canNext={table.getCanNextPage()}
          onPageChange={(page) => table.setPageIndex(page)}
        />
      </section>

      <DetalleInspectorPanel modo={modo} licitacion={detailWithScore} onClose={closeDetail} />

      <DetalleSeleccion
        seleccionadas={selectedIds.length}
        onComparar={() => setShowComparator(true)}
        onExportar={() =>
          downloadCsv(selectedItems, `seleccion_${new Date().toISOString().slice(0, 10)}.csv`)
        }
        onSeguir={() => {
          selectedIds.forEach((id) => favoritos.seguir(id));
          setRowSelection({});
        }}
        onLimpiar={() => setRowSelection({})}
      />

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
