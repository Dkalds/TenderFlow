/**
 * Ejecuta `fn` cuando el navegador esté ocioso; devuelve cómo cancelarlo.
 *
 * Es la manera de adelantar el código de lo que se va a usar casi seguro pero
 * no al pintar (la paleta de ⌘K, el formulario de alta de organización): llega
 * después de la primera pintura, así que no cuenta en el First Load ni compite
 * con él por la red.
 */
export function alQuedarOcioso(fn: () => void): () => void {
  if (typeof window.requestIdleCallback === "function") {
    const id = window.requestIdleCallback(fn, { timeout: 10_000 });
    return () => window.cancelIdleCallback(id);
  }
  // Safari no tiene `requestIdleCallback`: un margen fijo tras la carga.
  const id = window.setTimeout(fn, 3_000);
  return () => window.clearTimeout(id);
}
