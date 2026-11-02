/** Control o `\`: el navegador los descarta o los reinterpreta (`/\host` acaba siendo `//host`). */
function tieneControlOBarraInvertida(texto: string): boolean {
  for (let i = 0; i < texto.length; i += 1) {
    const codigo = texto.charCodeAt(i);
    if (codigo < 0x20 || codigo === 0x7f || codigo === 0x5c) return true;
  }
  return false;
}

/**
 * La URL tal cual si es un enlace seguro de pintar; `null` en cualquier otro caso.
 *
 * Es segura una URL absoluta `http(s)` o una ruta del propio sitio
 * (`/docs/pcap.pdf`: un solo `/` al principio, sin `\` ni caracteres de control).
 *
 * Las URI de los adjuntos (`DocumentoSummary.uri`) las escribe quien publica el
 * anuncio en PLACSP/TED: son texto de terceros. Antes de pintarlas en un
 * `href` se comprueba el esquema, para que un `javascript:` o un `data:` no
 * llegue a ser un enlace que alguien pueda pulsar, ni un `//host` pase por una
 * ruta interna.
 */
export function urlHttp(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith("/")) {
    return url.startsWith("//") || tieneControlOBarraInvertida(url) ? null : url;
  }
  try {
    const { protocol } = new URL(url);
    return protocol === "https:" || protocol === "http:" ? url : null;
  } catch {
    return null;
  }
}
