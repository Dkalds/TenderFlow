/**
 * Fixtures compartidos por los tests de la tabla de Detalle.
 *
 * Son datos, no mocks: `vi.mock` no puede vivir aquí (el hoisting es por
 * fichero de test), así que este módulo solo trae lo que se puede importar sin
 * trucos — la fila mínima y la paginación por defecto.
 */
import type { LicitacionSummary } from "@/lib/api-types";
import { PAGE_SIZE } from "../_hooks/detalle-table-model";

export function row(overrides: Partial<LicitacionSummary> & { id_externo: string }) {
  return {
    titulo: null,
    organo_contratacion: null,
    importe: null,
    estado: null,
    fecha_publicacion: null,
    ccaa: null,
    cpv: null,
    tecnologia: null,
    ...overrides,
  } as unknown as LicitacionSummary;
}

export const PAGINATION = { pageIndex: 0, pageSize: PAGE_SIZE };
