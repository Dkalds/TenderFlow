/**
 * La URL tal cual si es absoluta `http(s)`; `null` en cualquier otro caso.
 *
 * Las URI de los adjuntos (`DocumentoSummary.uri`) las escribe quien publica el
 * anuncio en PLACSP/TED: son texto de terceros. Antes de pintarlas en un
 * `href` se comprueba el esquema, para que un `javascript:` o un `data:` no
 * llegue a ser un enlace que alguien pueda pulsar.
 */
export function urlHttp(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const { protocol } = new URL(url);
    return protocol === "https:" || protocol === "http:" ? url : null;
  } catch {
    return null;
  }
}
