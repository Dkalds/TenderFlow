import type { Schemas, WatchlistRuleOut } from "@/lib/api-types";

/**
 * Qué cuenta como «hecho» en cada paso, leído del contrato de la API.
 *
 * Vive separado del hook a propósito: son predicados sobre respuestas del
 * servidor, la parte que de verdad puede equivocarse, y así se ejercitan sin
 * montar React ni doblar el cliente HTTP.
 */

/**
 * `GET /me/profile` devuelve un `UserProfileOut` **vacío** —no un 404— cuando el
 * usuario no tiene perfil, así que no vale con que la respuesta llegue: hay que
 * mirar si trae algo suyo dentro. Se aceptan todas las señales porque un perfil
 * creado antes de que existiera una dimensión puede no traer `weights`.
 */
export function perfilConfigurado(perfil: Schemas["UserProfileOut"]): boolean {
  return (
    perfil.updated_at != null ||
    (perfil.weights != null && Object.keys(perfil.weights).length > 0) ||
    (perfil.afinidad_keywords?.length ?? 0) > 0 ||
    (perfil.cpvs?.length ?? 0) > 0 ||
    perfil.importe_min != null ||
    perfil.importe_max != null
  );
}

/**
 * Una regla desactivada no vigila nada: el usuario no recibiría ni una señal por
 * ella, así que contarla como paso hecho sería darle por resuelto algo que no lo
 * está.
 */
export function hayReglaActiva(reglas: readonly WatchlistRuleOut[]): boolean {
  return reglas.some((regla) => regla.active);
}

/** El total lo cuenta el backend (`PursuitListResponse.total`), no el frontend. */
export function tienePursuits(listado: { total: number }): boolean {
  return listado.total > 0;
}
