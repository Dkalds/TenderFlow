/**
 * Export URL building + download triggering — shared by ExportPopover and the
 * command palette's "Acciones con filtros" group so both stay in sync with a
 * single source of truth for how export query params are assembled.
 */

import { toast } from "sonner";

import { dimensionesDeDescarga, registrarEvento, type EventosProducto } from "./analytics";

/**
 * Build a download URL for the given endpoint, combining the requested
 * format, the active filter params and any extra (page-specific) params as
 * query string parameters. Empty/nullish filter values are skipped.
 *
 * `format` es el valor que declara la API (`Literal["csv", "excel", "pdf"]` en
 * `api/routes/exports.py`), **no** la extensión del fichero: el Excel se pide
 * como `excel` y llega como `.xlsx`. Mandar `xlsx` aquí devuelve un 422.
 */
export function buildExportUrl(
  endpoint: string,
  format: "csv" | "excel",
  filterParams: Record<string, string>,
  extraParams?: Record<string, string>,
): string {
  const params = new URLSearchParams();
  params.set("format", format);

  if (filterParams) {
    for (const [key, value] of Object.entries(filterParams)) {
      if (value != null && value !== "") {
        params.set(key, String(value));
      }
    }
  }

  if (extraParams) {
    for (const [key, value] of Object.entries(extraParams)) {
      params.set(key, value);
    }
  }

  return `${endpoint}?${params.toString()}`;
}

/**
 * Nombre de fichero anunciado por el servidor en `Content-Disposition`.
 *
 * Al descargar desde un blob el navegador ya no ve la cabecera: el nombre lo
 * decide el atributo `download` del ancla. Sin esto, el Excel que la API llama
 * `licitaciones_20260828.xlsx` acabaría en la carpeta de descargas con el UUID
 * del object URL y sin extensión, que es peor que el bug que veníamos a
 * arreglar. Se prefiere `filename*` (RFC 5987) porque es el que trae los
 * acentos bien codificados.
 */
function nombreAnunciado(respuesta: Response): string | null {
  const cabecera = respuesta.headers.get("Content-Disposition");
  if (!cabecera) return null;

  const extendido = /filename\*=UTF-8''([^;]+)/i.exec(cabecera);
  if (extendido) {
    try {
      return decodeURIComponent(extendido[1].trim());
    } catch {
      // Porcentajes mal formados: caemos al `filename` simple de abajo.
    }
  }

  const simple = /filename="?([^";]+)"?/i.exec(cabecera);
  return simple ? simple[1].trim() : null;
}

/**
 * Vuelca un blob a la carpeta de descargas del usuario.
 *
 * Es la única parte que sigue necesitando el ancla invisible: no hay API de
 * navegador para "guardar esto" que funcione en todos los navegadores que
 * soportamos. El ancla se cuelga del documento porque Firefox ignora el click
 * sobre un nodo que no está en el árbol, y el object URL se libera acto seguido
 * para no dejar el blob retenido en memoria durante toda la sesión.
 */
function volcarBlob(nombre: string, blob: Blob): void {
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = nombre;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(objectUrl);
}

/**
 * Descarga `url` y la entrega al usuario como fichero.
 *
 * Antes esto era un `<a download>` a ciegas: el navegador se llevaba la
 * respuesta fuera del control de la aplicación, así que un 422 —el que devolvía
 * la API a todas las exportaciones a Excel— o un 401 por sesión caducada no se
 * distinguían de un éxito. No se veía nada: ni fichero, ni error. Pasar por
 * `fetch` es lo que permite mirar el estado antes de prometerle un fichero a
 * nadie; `credentials: "include"` porque la sesión va en cookie y el ancla la
 * mandaba sola.
 *
 * El evento se emite **después** del 200 y no antes, o la métrica cuenta como
 * exportación cada intento fallido — que era justamente lo que enmascaraba el
 * bug del formato. De la URL sólo se conserva formato y recurso: la query lleva
 * los filtros escritos por el usuario y no sale de este proceso (ver
 * `dimensionesDeDescarga`).
 */
export async function triggerDownload(url: string): Promise<void> {
  let respuesta: Response;
  try {
    respuesta = await fetch(url, { credentials: "include" });
  } catch {
    toast.error("No se pudo descargar el fichero", {
      description: "Sin conexión con el servidor. Revisá la red y volvé a intentarlo.",
    });
    return;
  }

  if (!respuesta.ok) {
    toast.error("No se pudo descargar el fichero", {
      description:
        respuesta.status === 401 || respuesta.status === 403
          ? "Tu sesión caducó. Volvé a entrar y repetí la exportación."
          : `El servidor respondió ${respuesta.status}. Probá con menos filas o avisá a soporte.`,
    });
    return;
  }

  const blob = await respuesta.blob();
  volcarBlob(nombreAnunciado(respuesta) ?? "export", blob);
  registrarEvento("export_lanzado", dimensionesDeDescarga(url));
}

/**
 * Recursos que se exportan generando el fichero en el propio navegador.
 *
 * Es una unión cerrada a propósito: `recurso` viaja a la telemetría, donde sólo
 * entran dimensiones categóricas enumerables leyendo el código (regla 1 de
 * `lib/analytics.ts`). Un `string` libre aquí sería la puerta por la que se
 * cuela un identificador.
 */
export type RecursoDescargaLocal = "detalle" | "investigador" | "adjudicaciones-empresa";

/** Formato de la métrica deducido de la extensión del fichero generado. */
function formatoDeNombre(nombre: string): EventosProducto["export_lanzado"]["formato"] {
  const minusculas = nombre.toLowerCase();
  if (minusculas.endsWith(".csv")) return "csv";
  if (minusculas.endsWith(".xlsx")) return "xlsx";
  return "otro";
}

/**
 * Entrega al usuario un fichero construido en el cliente, midiéndolo.
 *
 * Tres pantallas (Detalle, Investigador y el histórico de adjudicaciones de una
 * empresa) arman su CSV en el navegador con los datos que ya tienen en pantalla
 * y nunca pasan por `triggerDownload`, así que durante meses sus descargas no
 * emitieron ningún evento: la métrica de exportación medía sólo las de la API y
 * se leía como si fuera el total. `recurso` lo pone quien llama porque aquí no
 * hay URL de la que deducirlo.
 *
 * Las descargas de datos personales (`mi-cuenta`, `mi-perfil`) **no** usan esto
 * ni deben usarlo: son un derecho RGPD, no uso de producto, y contarlas mezcla
 * las dos cosas.
 */
export function descargarBlob(nombre: string, blob: Blob, recurso: RecursoDescargaLocal): void {
  volcarBlob(nombre, blob);
  registrarEvento("export_lanzado", { formato: formatoDeNombre(nombre), recurso });
}
