"use client";

/**
 * Abrir la ficha de una licitación sin salir de la pantalla (CU-02).
 *
 * Hasta 2026-11 cada lista de la consola (Resumen, Watchlist, Competencia,
 * Cuentas…) enlazaba a `/detalle?lic=`: mirar una licitación te sacaba de la
 * lista, y mirar la siguiente obligaba a volver atrás. Ahora el clic abre la
 * ficha en un panel lateral (`FichaFlotante`) junto a la misma pantalla —desde
 * `xl` la desplaza, por debajo se superpone—, que sigue siendo pulsable: otro
 * clic cambia la ficha.
 *
 * El `href` sigue apuntando a `/detalle?lic=`: Ctrl/⌘-clic, el botón central y
 * «Abrir en una pestaña nueva» llevan a la ficha de siempre. En `/detalle` el
 * enlace navega como antes, porque allí `?lic=` ya abre su propio inspector.
 *
 * Abrir es un `history.pushState` con `?ver=`, que el App Router sincroniza con
 * `useSearchParams` sin pedir la página al servidor: atrás cierra el panel. El
 * enlace no usa hooks: vive en una veintena de listas y sus tests.
 */
import * as React from "react";
import Link from "next/link";
import { parseAsString, useQueryState } from "nuqs";

/** Parámetro de la ficha flotante; distinto del `lic` de `/detalle`. */
export const PARAMETRO_FICHA_FLOTANTE = "ver";

export function rutaFicha(idExterno: string): string {
  return `/detalle?lic=${encodeURIComponent(idExterno)}`;
}

/**
 * Abrir una ficha desde código (un clic en un gráfico, una fila con `onClick`).
 * En `/detalle` cambia su `?lic=`; en el resto, el panel.
 */
export function abrirFicha(idExterno: string) {
  const url = new URL(window.location.href);
  url.searchParams.set(url.pathname === "/detalle" ? "lic" : PARAMETRO_FICHA_FLOTANTE, idExterno);
  window.history.pushState(null, "", url);
}

/** La ficha flotante abierta, como estado de la URL. Lo lee el panel. */
export function useFichaFlotante() {
  return useQueryState(PARAMETRO_FICHA_FLOTANTE, parseAsString.withOptions({ history: "push", shallow: true }));
}

/**
 * El `onClick` de un enlace a `rutaFicha(id)`: el clic normal abre el panel; el
 * que lleva modificador o botón central sigue al `href`, y en `/detalle` el
 * enlace navega como siempre. Para los enlaces que ya tienen su componente
 * (`EnlaceIr`); los demás usan `EnlaceFicha`.
 */
export function alPulsarFicha(evento: React.MouseEvent, idExterno: string) {
  const conModificador = evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey;
  if (evento.defaultPrevented || evento.button !== 0 || conModificador) return;
  if (window.location.pathname === "/detalle") return;
  evento.preventDefault();
  abrirFicha(idExterno);
}

type EnlaceFichaProps = Omit<React.ComponentProps<typeof Link>, "href"> & { idExterno: string };

export function EnlaceFicha({ idExterno, onClick, ...props }: EnlaceFichaProps) {
  return (
    <Link
      {...props}
      href={rutaFicha(idExterno)}
      onClick={(evento) => {
        onClick?.(evento);
        alPulsarFicha(evento, idExterno);
      }}
    />
  );
}
