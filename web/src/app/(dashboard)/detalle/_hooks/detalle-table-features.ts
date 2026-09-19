import {
  rowPaginationFeature,
  rowSelectionFeature,
  rowSortingFeature,
  tableFeatures,
} from "@tanstack/react-table";

/**
 * Features de v9 que usa la tabla de Detalle.
 *
 * Orden y paginación son manuales (los resuelve el servidor), así que se
 * registran las features para disponer de su estado y sus métodos pero sin
 * row model: registrar `sortedRowModel`/`paginatedRowModel` aquí volvería a
 * ordenar y a recortar en cliente una página que ya viene hecha.
 */
export const detalleTableFeatures = tableFeatures({
  rowSortingFeature,
  rowPaginationFeature,
  rowSelectionFeature,
});
