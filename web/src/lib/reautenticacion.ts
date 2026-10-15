/**
 * El 403 de «vuelve a entrar» (`require_recent_session` en la API).
 *
 * Las acciones sensibles —activar o quitar el segundo factor, acuñar, rotar o
 * revocar claves, borrar una organización— solo se aceptan poco después de
 * iniciar sesión. Pasado ese margen la API responde 403 con un `type` propio
 * (`TIPO_REAUTENTICACION` en `api/errors.py`), y ese 403 tiene arreglo: cerrar
 * sesión y volver a entrar. Decir «no tienes permiso» sería falso, y el texto
 * en inglés del `detail` no es contrato de nada.
 */
import { apiMutate, ApiError } from "@/lib/api-client";
import { reportError } from "@/lib/report-error";

/** Identificador del contrato de errores, no una URL que se pida. */
export const TIPO_REAUTENTICACION = "https://licitaciones-sap/errors/reauthentication-required";

/** ¿El fallo se arregla volviendo a entrar? */
export function pideReautenticacion(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && error.tipo === TIPO_REAUTENTICACION;
}

/** El login, con la vuelta a esta misma pantalla y vista (`?redirect=`). */
export function destinoTrasVolver(ruta: string, consulta: string): string {
  return `/login?redirect=${encodeURIComponent(ruta + consulta)}`;
}

/**
 * Cierra la sesión y lleva al login con la vuelta preparada.
 *
 * Cerrarla primero no es un detalle: con la cookie viva el login ofrece
 * «Continuar» con la misma sesión antigua (`sesion-abierta.tsx`), y el 403
 * volvería a salir. `irA` existe para los tests; por defecto es una navegación
 * completa, que además vacía la caché de la sesión anterior.
 */
export async function volverAEntrar(
  irA: (destino: string) => void = (destino) => {
    window.location.href = destino;
  },
): Promise<void> {
  try {
    await apiMutate("POST", "/api/v1/auth/logout");
  } catch (error) {
    // Aunque falle, se va al login: allí la sesión se comprueba de nuevo.
    reportError("volverAEntrar.logout", error);
  }
  irA(destinoTrasVolver(window.location.pathname, window.location.search));
}
