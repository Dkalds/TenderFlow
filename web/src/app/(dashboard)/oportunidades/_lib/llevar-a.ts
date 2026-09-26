/**
 * Lleva la vista a un panel de la ficha y le da el foco.
 *
 * Desplaza solo el contenedor con scroll más cercano, y no con
 * `scrollIntoView`: ése desplaza también el documento cuando algo lo desborda
 * —los `<select>` ocultos que monta Radix lo hacen—, y la cabecera de la ficha
 * se salía de la pantalla. El contenedor se busca en cada llamada porque no es
 * el mismo en todos los anchos. Sin animación si el sistema pide movimiento
 * reducido: el salto es consecuencia de un clic, no una transición que ver.
 */

/** Aire sobre el panel al llegar, el mismo que el relleno del contenedor. */
const MARGEN = 16;

function contenedorConScroll(elemento: HTMLElement): HTMLElement | null {
  for (let nodo = elemento.parentElement; nodo; nodo = nodo.parentElement) {
    const { overflowY } = getComputedStyle(nodo);
    if ((overflowY === "auto" || overflowY === "scroll") && nodo.scrollHeight > nodo.clientHeight) return nodo;
  }
  return null;
}

export function llevarA(id: string): void {
  const destino = document.getElementById(id);
  if (!destino) return;
  const contenedor = contenedorConScroll(destino);
  if (contenedor) {
    const reducido = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const desplazamiento = destino.getBoundingClientRect().top - contenedor.getBoundingClientRect().top;
    contenedor.scrollTo({
      top: contenedor.scrollTop + desplazamiento - MARGEN,
      behavior: reducido ? "auto" : "smooth",
    });
  }
  destino.focus({ preventScroll: true });
}
