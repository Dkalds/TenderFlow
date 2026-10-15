/**
 * Reglas de los adjuntos propios de una oportunidad, **leídas de la API**.
 *
 * El tope por fichero y la lista blanca de tipos los dicta el servidor
 * (`GET /pursuits/adjuntos/politica`, que sale de las mismas constantes con las
 * que valida la subida). Aquí no hay ninguna copia de esas constantes: estas
 * funciones solo aplican la política recibida para avisar **antes** de enviar
 * un fichero que el servidor va a rechazar, y para elegir el `Content-Type`.
 *
 * Por qué el tipo se deduce de la extensión y no de `File.type`: el navegador
 * rellena `File.type` con lo que diga el sistema operativo, y Windows llama
 * `application/vnd.ms-excel` a un `.csv`. El servidor exige que tipo y
 * extensión concuerden, así que mandar el `File.type` tal cual hacía fallar
 * ficheros perfectamente admitidos.
 */
import type { Schemas } from "@/lib/api-types";
import { formatTamano } from "@/lib/utils";

export type PoliticaAdjuntos = Schemas["PursuitAttachmentPolicy"];
export type Adjunto = Schemas["PursuitAttachmentOut"];

/** Extensión en minúsculas con su punto («.pdf»), o cadena vacía si no tiene. */
export function extensionDe(nombre: string): string {
  const punto = nombre.lastIndexOf(".");
  if (punto <= 0 || punto === nombre.length - 1) return "";
  return nombre.slice(punto).toLowerCase();
}

/** Todas las extensiones admitidas, ordenadas: para el `accept` y para el texto. */
export function extensionesAdmitidas(politica: PoliticaAdjuntos): string[] {
  return [...new Set(politica.tipos.flatMap((tipo) => tipo.extensiones))].sort();
}

/** El tipo de la lista blanca al que corresponde el nombre, o `null`. */
export function tipoDeFichero(nombre: string, politica: PoliticaAdjuntos): string | null {
  const extension = extensionDe(nombre);
  if (!extension) return null;
  return politica.tipos.find((tipo) => tipo.extensiones.includes(extension))?.content_type ?? null;
}

export type ValidacionFichero = { ok: true; contentType: string } | { ok: false; motivo: string };

/**
 * ¿Lo va a aceptar el servidor? Mismo orden que `services/pursuit_attachments
 * .validar`: vacío, tamaño, tipo. El servidor lo vuelve a comprobar todo; esto
 * solo ahorra subir 25 MiB para oír que no.
 */
export function validarFichero(
  fichero: { name: string; size: number },
  politica: PoliticaAdjuntos,
): ValidacionFichero {
  if (fichero.size <= 0) return { ok: false, motivo: "El fichero está vacío." };
  if (fichero.size > politica.max_bytes) {
    return {
      ok: false,
      motivo: `Ocupa ${formatTamano(fichero.size)} y el máximo es ${formatTamano(politica.max_bytes)}.`,
    };
  }
  const contentType = tipoDeFichero(fichero.name, politica);
  if (!contentType) {
    return {
      ok: false,
      motivo: `Ese tipo de fichero no se admite. Se admiten: ${extensionesAdmitidas(politica).join(", ")}.`,
    };
  }
  return { ok: true, contentType };
}

/**
 * El nombre tal como viaja en `X-Filename`: codificado como URI. Una cabecera
 * HTTP solo lleva Latin-1 y `fetch` lanza ante una raya larga o un «ł»; el
 * servidor lo decodifica antes de sanearlo.
 */
export function nombreParaCabecera(nombre: string): string {
  return encodeURIComponent(nombre);
}
