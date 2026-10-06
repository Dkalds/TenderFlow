"use client";

import { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { parseAsString, useQueryState } from "nuqs";
import { useTable } from "@tanstack/react-table";
import { useFiltroEtiqueta } from "@/components/etiquetas/filtro-etiqueta";
import { useDensity } from "@/lib/density";
import { useFilterParams, useFilters } from "@/lib/filters";
import { toggleValue } from "@/lib/chart-interaction";
import { useModoInspector } from "../radar/_hooks/use-media-query";
import { DetalleBarra } from "./_components/detalle-barra";
import { COLUMNS, etiquetaDeOrden } from "./_components/detalle-columnas";
import { DetalleComparador } from "./_components/detalle-comparador";
import { DetallePie, lineaMostrando } from "./_components/detalle-pie";
import { DetalleSeleccion, descargarSeleccion } from "./_components/detalle-seleccion";
import { DetalleTabla } from "./_components/detalle-tabla";
import { detalleTableFeatures } from "./_hooks/detalle-table-features";
import { useBusquedaListado } from "./_hooks/use-busqueda-listado";
import { useCierreRecorte } from "./_hooks/use-cierre-recorte";
import { useDetalleFavoritos } from "./_hooks/use-detalle-favoritos";
import { useDetalleQueries, useDetailWithScore } from "./_hooks/use-detalle-queries";
import { useDetalleRows, useDetalleTableState } from "./_hooks/use-detalle-table";
import { useDetalleTeclado } from "./_hooks/use-detalle-teclado";
import { pasosDeFicha, useFichaCompleta } from "./_hooks/use-ficha-completa";

/**
 * Detalle — tabla de trabajo con inspector en el mismo plano.
 *
 * La pantalla mantiene sus 28 capacidades; lo que cambia es dónde vive la
 * ficha. Antes era un Sheet modal que apilaba once bloques encima de la tabla,
 * así que comparar dos licitaciones exigía abrir, leer, cerrar y volver a
 * abrir. Ahora el inspector (`components/detail-inspector.tsx`) convive con la
 * tabla y reparte esos once bloques en cinco pestañas. Desde el inspector se abre
 * la ficha completa (`?ficha=completa`), que ocupa el sitio de la tabla con
 * todo a la vez; por debajo de `md`, donde no hay inspector, es la ficha.
 *
 * La tabla conserva las catorce columnas, el orden asc/desc/none con cabecera
 * pegajosa, la selección múltiple con select-all, el punto de «nueva», la
 * estrella de watchlist, el cross-filter desde CCAA y Tecnología, la densidad,
 * la paginación completa con contador, la exportación y los estados de carga,
 * vacío y error.
 *
 * Esta pantalla es la composición: el estado y las consultas viven en
 * `_hooks/`, cada bloque de UI en `_components/`.
 */

// El inspector no pinta nada hasta que se abre una fila, y arrastra los once
// bloques de la ficha (IA, documentos, eventos). Fuera del First Load de la
// tabla, que es lo que se mide al entrar.
const DetalleInspectorPanel = dynamic(() =>
  import("./_components/detalle-inspector-panel").then((modulo) => modulo.DetalleInspectorPanel),
);
// La ficha completa arrastra los mismos bloques: tampoco entra en el First Load.
const DetalleFichaCompleta = dynamic(() =>
  import("./_components/detalle-ficha-completa").then((modulo) => modulo.DetalleFichaCompleta),
);

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
  const ficha = useFichaCompleta({ modo, detailId });

  const queries = useDetalleQueries({
    queryParams: tabla.queryParams,
    detailId,
    errorDetalleEnLinea: ficha.activa,
  });
  useBusquedaListado(queryFilters, queries.data, queries.isFetching);

  // Cursor de la siguiente, aprendido de ésta (nunca del `placeholderData` de la anterior).
  const { registrarSiguiente } = tabla;
  const siguienteCursor = queries.isPlaceholderData ? undefined : queries.data?.next_cursor;
  useEffect(
    () => registrarSiguiente(pagination.pageIndex, siguienteCursor),
    [registrarSiguiente, pagination.pageIndex, siguienteCursor],
  );

  // Orden en cliente sólo para columnas que el backend no ordena (`clientSorted`):
  // es sobre la página cargada, no sobre el total, y el pie lo dice.
  const filas = useDetalleRows({
    items: queries.data?.items,
    total: queries.data?.total,
    scoring: queries.scoring,
    lastViewed: favoritos.lastViewed,
    activeSort: tabla.activeSort,
    pagination,
    rowSelection,
    alcanzables: tabla.alcanzables,
    setRowSelection,
  });
  const { mergedRows: filasPagina, totalPages, selectedIds, selectedItems } = filas;
  // F1.6 — filtra la página cargada: `GET /licitaciones` no acepta etiqueta.
  const etiqueta = useFiltroEtiqueta("favorito", filasPagina.map((row) => row.id_externo));
  const pasaEtiqueta = etiqueta.pasa;
  const mergedRows = useMemo(() => filasPagina.filter((row) => pasaEtiqueta(row.id_externo)), [filasPagina, pasaEtiqueta]);
  const total = queries.data?.total ?? 0;

  const table = useTable({
    features: detalleTableFeatures,
    data: mergedRows,
    columns: useMemo(() => COLUMNS.map((column) => ({ id: column.key })), []),
    state: { sorting, pagination, rowSelection },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    onRowSelectionChange: setRowSelection,
    // Sin row models de orden/página: el servidor ya devuelve la página
    // ordenada, así que sólo se registran las features para tener su estado y
    // sus métodos. El core row model en v9 es automático.
    manualSorting: true,
    manualPagination: true,
    pageCount: totalPages,
    getRowId: (row) => row.id_externo,
    enableRowSelection: true,
  });

  const openDetail = useCallback((id: string) => void setDetailId(id), [setDetailId]);

  const { cerrar: cerrarFichaCompleta } = ficha;
  const closeDetail = useCallback(() => {
    // startTransition: cerrar desmonta bloques pesados (IA, documentos,
    // eventos); diferirlo evita bloquear el hilo principal en el propio clic.
    startTransition(() => {
      void setDetailId(null, { history: "replace" });
      cerrarFichaCompleta();
    });
  }, [setDetailId, cerrarFichaCompleta]);
  // Volver de la ficha completa: al inspector donde lo hay; en móvil, a la tabla.
  const volverATabla = ficha.enMovil ? closeDetail : cerrarFichaCompleta;

  const { cursor, setCursor } = useDetalleTeclado({
    mergedRows,
    detailId,
    showComparator,
    closeComparator,
    closeDetail: ficha.activa ? volverATabla : closeDetail,
    openDetail,
    toggleFavorite: favoritos.toggleFavorite,
    fichaCompleta: ficha.activa,
  });

  const detailWithScore = useDetailWithScore(queries.detailData, filas.scoreMap);
  const isEmpty = !queries.isLoading && !queries.error && mergedRows.length === 0;

  const sortLabel = etiquetaDeOrden(sorting);
  const showingLine = lineaMostrando({ hayDatos: Boolean(queries.data), ...pagination, total });

  return (
    <div className="flex h-full min-h-0">
      {ficha.activa && detailId ? (
        <DetalleFichaCompleta
          idExterno={detailId}
          licitacion={detailWithScore}
          error={queries.detailError}
          onReintentar={queries.refetchDetail}
          pasos={pasosDeFicha(mergedRows, detailId)}
          onIr={(paso) => {
            setCursor(paso.indice);
            openDetail(paso.id);
          }}
          onVolver={volverATabla}
        />
      ) : (
        <>
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
              etiqueta={etiqueta}
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
              ccaas={ccaas}
              tecnologias={tecnologias}
              compact={compact}
              rowHeight={compact ? 34 : 44}
              onOpen={(index, id) => {
                setCursor(index);
                openDetail(id);
              }}
              onToggleSelect={tabla.toggleRow}
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
              canNext={pagination.pageIndex + 1 < tabla.alcanzables}
              canLast={totalPages - 1 < tabla.alcanzables && pagination.pageIndex < totalPages - 1}
              onPageChange={tabla.irAPagina}
            />
          </section>

          <DetalleInspectorPanel
            modo={modo}
            licitacion={detailWithScore}
            onClose={closeDetail}
            onExpandir={ficha.abrir}
          />
        </>
      )}

      <DetalleSeleccion
        seleccionadas={selectedIds.length}
        onComparar={() => setShowComparator(true)}
        onExportar={() => descargarSeleccion(selectedItems)}
        onSeguir={() => {
          selectedIds.forEach((id) => favoritos.seguir(id));
          setRowSelection({});
        }}
        onLimpiar={() => setRowSelection({})}
      />

      {showComparator && selectedItems.length >= 2 && (
        <DetalleComparador
          filas={selectedItems}
          onClose={() => startTransition(() => setShowComparator(false))}
        />
      )}
    </div>
  );
}
