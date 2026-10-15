/**
 * Piezas puras del alta y la baja del segundo factor (Ajustes › Seguridad).
 *
 * Sin QR: no hay librería de QR en el proyecto, y meter una para esto no
 * compensa. La app del móvil acepta la clave tecleada, y en el propio móvil el
 * enlace `otpauth://` la abre directamente; las dos salen del URI que entrega
 * `POST /auth/totp/setup`, que es lo único que trae.
 */
import { ApiError } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/query-feedback";

/**
 * La clave base32 del URI `otpauth://`, o `null` si no la trae. Se lee a mano
 * y no con `new URL`: el esquema no es web y cada motor lo trata a su manera.
 */
export function secretoDeUri(uri: string): string | null {
  const consulta = uri.split("?")[1];
  if (!consulta) return null;
  return new URLSearchParams(consulta).get("secret") || null;
}

/** «JBSWY3DPEHPK3PXP» → «JBSW Y3DP EHPK 3PXP»: se teclea sin perder el sitio. */
export function agruparSecreto(secreto: string): string {
  return secreto.match(/.{1,4}/g)?.join(" ") ?? secreto;
}

/** Quita espacios y guiones: la gente copia el código como lo ve. */
export function limpiarCodigo(valor: string): string {
  return valor.replace(/[\s-]/g, "");
}

/** Seis cifras: el código de la app. */
export function codigoTotpValido(codigo: string): boolean {
  return /^\d{6}$/.test(codigo);
}

/** Dieciséis caracteres hexadecimales: uno de los códigos de recuperación. */
export function codigoDeRecuperacionValido(codigo: string): boolean {
  return /^[0-9a-f]{16}$/i.test(codigo);
}

/**
 * Lo que se le dice a la persona cuando la API rechaza un paso. El `detail`
 * de estos endpoints está en inglés («Invalid TOTP code»), así que los dos
 * casos que dependen de ella se cuentan aquí con lo que puede hacer.
 */
export function mensajeDelSegundoFactor(error: unknown): string {
  if (error instanceof ApiError && error.status === 400) {
    return "El código no es válido. Comprueba que la hora del móvil está en automático y prueba con el siguiente.";
  }
  if (error instanceof ApiError && error.status === 429) {
    return "Demasiados códigos fallidos seguidos. Espera unos minutos antes de volver a probar.";
  }
  return getErrorMessage(error, "accion");
}
