/**
 * Qué se enseña cuando falla una entrada en `/login`, y qué se ofrece con ello.
 *
 * Vive aparte del hook (`_hooks/use-login-form.ts`) para que el hook decida el
 * flujo y esto, el texto: los 403 de la concesión de acceso (RFC
 * 2026-10-21-alta-con-contrasena-tras-concesion) traen un código
 * (`access_not_granted`, `email_not_verified`) que no se enseña tal cual, y
 * cada uno pide una salida distinta.
 */

import { ApiError, MENSAJE_SIN_CONEXION } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/query-feedback";

/**
 * Lo que acompaña a un error cuando hay algo que hacer con él, además de leerlo:
 * pedir el acceso que falta, o pedir otro enlace de activación.
 */
export type AccionError = "solicitar_acceso" | "reenviar_enlace";

export interface Fallo {
  texto: string;
  accion?: AccionError;
}

/** `detail` de los 403 de `/auth/login` y `/auth/register` (`api/routes/auth.py`). */
const SIN_ACCESO = "access_not_granted";
const SIN_VERIFICAR = "email_not_verified";

const OAUTH_FALLBACK_ERROR = "No se pudo completar el inicio de sesión. Inténtalo de nuevo.";

const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  invalid_state: "La sesión de inicio caducó o ya se usó. Inténtalo de nuevo.",
  oauth_failed: OAUTH_FALLBACK_ERROR,
  email_not_allowed: "Tu cuenta no tiene acceso a TenderFlow.",
  // El correo ya es de una cuenta que entra con otro proveedor (ADR-037).
  account_other_provider:
    "Ese correo ya tiene cuenta con otro proveedor: entra con el que usaste la primera vez.",
};

/** El `?error=` con el que vuelve el callback de OAuth, o `null` si no hay. */
export function falloDelCallback(codigo: string | null): Fallo | null {
  return codigo ? { texto: OAUTH_ERROR_MESSAGES[codigo] ?? OAUTH_FALLBACK_ERROR } : null;
}

/** ¿El 403 es este, y no otro 403 cualquiera? */
function es403(err: ApiError, detail: string): boolean {
  return err.status === 403 && err.message === detail;
}

/*
 * El mismo texto que el resto de la aplicación para el mismo fallo. El resto
 * de errores de la API pasan por `getErrorMessage(…, "accion")`: el `detail`
 * cuando explica qué falló de lo pedido, y un mensaje humano en los 5xx en vez
 * del texto crudo del servidor.
 */
function falloGenerico(err: unknown): Fallo {
  return { texto: err instanceof ApiError ? getErrorMessage(err, "accion") : MENSAJE_SIN_CONEXION };
}

/** Fallo de `POST /auth/login`. */
export function falloDelAcceso(err: unknown): Fallo {
  if (!(err instanceof ApiError)) return falloGenerico(err);
  if (err.status === 401) return { texto: "Credenciales incorrectas." };
  // La contraseña es buena pero la cuenta nunca se activó. El enlace nuevo sale
  // repitiendo el alta con el mismo correo (la API invalida los anteriores),
  // así que se ofrece eso y no un callejón.
  if (es403(err, SIN_VERIFICAR)) {
    return {
      texto: "Todavía no has activado la cuenta: abre el enlace que te enviamos al correo.",
      accion: "reenviar_enlace",
    };
  }
  if (es403(err, SIN_ACCESO))
    return { texto: "Tu cuenta ya no tiene acceso a TenderFlow.", accion: "solicitar_acceso" };
  return falloGenerico(err);
}

/** Fallo de `POST /auth/totp/verify`. */
export function falloDelSegundoFactor(err: unknown): Fallo {
  if (!(err instanceof ApiError)) return falloGenerico(err);
  if (err.status === 429) return { texto: "Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo." };
  if (err.status === 401) return { texto: "Código incorrecto. Revisa tu app de autenticación." };
  return falloGenerico(err);
}

/** Fallo de `POST /auth/register`. */
export function falloDelAlta(err: unknown): Fallo {
  if (!(err instanceof ApiError)) return falloGenerico(err);
  if (es403(err, SIN_ACCESO)) {
    return { texto: "Este correo no tiene acceso a TenderFlow todavía.", accion: "solicitar_acceso" };
  }
  // 409 solo en el alta abierta: el cerrado no dice si la cuenta existe. El
  // 400 (contraseña fuera de política) y el 429 traen su `detail`.
  if (err.status === 409) return { texto: "Este correo ya está registrado." };
  return falloGenerico(err);
}
