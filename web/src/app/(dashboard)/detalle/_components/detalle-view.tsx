"use client";

import { startTransition, useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { parseAsString, useQueryState } from "nuqs";
import { useDensity } from "@/lib/density";
import { useFilters } from "@/lib/filters";
import { toggleValue } from "@/lib/chart-interaction";
import { useModoInspector } from "../../radar/_hooks/use-media-query";
import { DetalleBarra } from "./detalle-barra";
import { etiquetaDeOrden } from "./detalle-columnas";
import { DetallePie, lineaMostrando } from "./detalle-pie";
import { DetalleTabla } from "./detalle-tabla";
import { useBusquedaListado } from "../_hooks/use-busqueda-listado";
import { useDetalleFavoritos } from "../_hooks/use-detalle-favoritos";
import { useDetalleQueries, useDetailWithScore } from "../_hooks/use-detalle-queries";
import { useDetalleRows, useDetalleTableState } from "../_hooks/use-detalle-table";
import { useDetalleTeclado } from "../_hooks/use-detalle-teclado";
import { useFiltrosDelListado } from "../_hooks/use-filtros-listado";
import { pasosDeFicha, useFichaCompleta } from "../_hooks/use-ficha-completa";
import { PARAMETRO_FICHA } from "../_lib/prefetch";

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
  import("./detalle-inspector-panel").then((modulo) => modulo.DetalleInspectorPanel),
);
// La ficha completa arrastra los mismos bloques: tampoco entra en el First Load.
const DetalleFichaCompleta = dynamic(() =>
  import("./detalle-ficha-completa").then((modulo) => modulo.DetalleFichaCompleta),
);
// El comparador solo existe con dos filas seleccionadas y tras pulsar
// «Comparar»: su diálogo (Radix Dialog) y sus tablas llegan entonces.
const DetalleComparador = dynamic(() =>
  import("./detalle-comparador").then((modulo) => modulo.DetalleComparador),
);
// La barra de selección solo existe con filas marcadas. Exportar desde ella
// importa el mismo módulo, que para entonces ya está descargado.
const DetalleSeleccion = dynamic(
  () => import("./detalle-seleccion").then((modulo) => modulo.DetalleSeleccion),
  { ssr: false },
);

export function DetalleView() {
  const { q, ccaas, setCcaas, tecnologias, setTecnologias, resetFilters } = useFilters();
  const toggleCcaa = useCallback(
    (ccaa: string) => setCcaas(toggleValue(ccaa, ccaas)),
    [ccaas, setCcaas],
  );
  const toggleTecnologia = useCallback(
    (tec: string) => setTecnologias(toggleValue(tec, tecnologias)),
    [tecnologias, setTecnologias],
  );

  // Ámbito global, recorte por ventana de cierre y etiqueta: lo mismo que pide
  // el prefetch en servidor (`_lib/prefetch.ts`).
  const { cierre, etiqueta, queryFilters } = useFiltrosDelListado();

  const tabla = useDetalleTableState({ filterParams: queryFilters, q });
  const { sorting, setSorting, pagination, setPagination, rowSelection, setRowSelection } = tabla;

  // Permalink de la ficha: ?lic=<id_externo>, con push al historial (atrás
  // cierra el inspector) y URL compartible desde cualquier fila.
  const [detailId, setDetailId] = useQueryState(
    PARAMETRO_FICHA,
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
  const { mergedRows, totalPages, selectedIds, selectedItems } = filas;
  const total = queries.data?.total ?? 0;

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
          <section className="flex min-w-0 flex-1 flex-col border-r border-divider">
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
              canPrevious={pagination.pageIndex > 0}
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
        onExportar={() => void import("./detalle-seleccion").then((modulo) => modulo.descargarSeleccion(selectedItems))}
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
