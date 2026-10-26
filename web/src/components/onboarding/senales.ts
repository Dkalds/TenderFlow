import type { Schemas } from "@/lib/api-types";

/**
 * Qué cuenta como «hecho» en cada paso, leído del contrato de la API.
 *
 * Vive separado del hook a propósito: son predicados sobre respuestas del
 * servidor, la parte que de verdad puede equivocarse, y así se ejercitan sin
 * montar React ni doblar el cliente HTTP.
 */

/** Las familias de capacidad que pide el primer paso, además del NIF. */
const FAMILIAS_DEL_PASO = ["certificaciones", "facturacion"] as const;

/**
 * ¿Faltan certificaciones o facturación en el perfil de capacidad?
 *
 * Lo decide el backend con `campos_incompletos`
 * (`GET /organizations/{id}/capabilities`), no este fichero: «certificaciones»
 * cuenta solo las técnicas, porque con únicamente documentación administrativa
 * el checklist sigue contestando «desconocido» en esa familia. Referencias y
 * perfiles de equipo también los marca el backend, pero el paso no los exige:
 * son el siguiente nivel, no el mínimo para que el checklist diga algo.
 */
export function faltaCapacidad(capacidad: Schemas["OrganizationCapabilitiesOut"]): boolean {
  const incompletos = capacidad.campos_incompletos ?? [];
  return FAMILIAS_DEL_PASO.some((familia) => incompletos.includes(familia));
}

/** Al menos un NIF declarado: sin él, el cierre por NIF no reconoce lo ganado. */
export function hayNif(nifs: Schemas["OrganizationNifsOut"]): boolean {
  return (nifs.nifs ?? []).length > 0;
}

/**
 * El paso es **revisar** la alerta, no crearla (B1 la crea al guardar las
 * tecnologías de la organización): hecho en cuanto hay una regla, también si
 * quien la revisó decidió pausarla.
 */
export function hayRegla(reglas: readonly unknown[]): boolean {
  return reglas.length > 0;
}

/** El total lo cuenta el backend (`PursuitListResponse.total`), no el frontend. */
export function tienePursuits(listado: { total: number }): boolean {
  return listado.total > 0;
}
