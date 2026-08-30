"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { useAnnounce } from "@/components/live-region";
import { ScrollEdgeSentinel } from "@/components/layout/scroll-edge";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { useDensity } from "@/lib/density";

/**
 * Título accesible de la página actual.
 *
 * 18 de las 33 páginas del dashboard no tenían ningún `<h1>` —incluidas Radar,
 * Detalle, Oportunidades, Mi Watchlist y Competidores—, así que un lector de
 * pantalla no obtenía título de página al navegar. Resolverlo aquí, y no con un
 * parche por página, garantiza que exista exactamente uno y que siga al mapa de
 * espacios en vez de duplicarse a mano en cada ruta nueva.
 *
 * Las páginas que ya pintan su propio `<h1>` visible lo mantienen: este va
 * oculto visualmente (`sr-only`) y el orden del DOM lo deja como primer
 * encabezado, que es lo que anuncia el lector.
 */
function usePageTitle(): string {
  const pathname = usePathname();
  const slug = (pathname ?? "").split("/").filter(Boolean)[0] ?? "";
  const space = CONSOLE_SPACES.find((s) => s.slug === slug);
  return space?.label ?? "TenderFlow";
}

/**
 * Anuncia la pantalla nueva y lleva el foco al contenido.
 *
 * La consola navega en cliente entre catorce espacios: al activar un destino
 * del rail el contenido se sustituye entero, pero el foco se quedaba en el
 * enlace y no se anunciaba nada. Quien usa lector de pantalla no recibía señal
 * de que la pantalla había cambiado, y quien navega con teclado tenía que
 * recorrer otra vez toda la navegación para llegar al contenido — en cada
 * salto, catorce veces por sesión.
 *
 * Las dos piezas ya existían y no se usaban: la región `aria-live` única de
 * `components/live-region.tsx` y el `#main-content` con `tabIndex={-1}` de este
 * mismo componente, que se puso como destino del skip link.
 *
 * El primer render NO anuncia: al entrar, el lector ya está leyendo la página.
 * Anunciar ahí duplicaría el título en vez de informar de un cambio.
 */
function useAnunciarCambioDePantalla(titulo: string, ref: React.RefObject<HTMLElement | null>) {
  const anunciar = useAnnounce();
  const pathname = usePathname();
  const anterior = React.useRef<string | null>(null);

  React.useEffect(() => {
    if (anterior.current !== null && anterior.current !== pathname) {
      anunciar(titulo);
      // `preventScroll`: el foco es consecuencia de la navegación, no una
      // petición del usuario de ir a ningún sitio. Sin esto, mover el foco
      // arrastraría el scroll y se perdería la posición que Next restaura.
      ref.current?.focus({ preventScroll: true });
    }
    anterior.current = pathname;
  }, [pathname, titulo, anunciar, ref]);
}

export function DashboardShell({ children }: { children: React.ReactNode }) {
  useKeyboardShortcuts();
  const compact = useDensity((s) => s.compact);
  const pageTitle = usePageTitle();
  const mainRef = React.useRef<HTMLElement>(null);
  useAnunciarCambioDePantalla(pageTitle, mainRef);

  return (
    <main
      ref={mainRef}
      id="main-content"
      // Destino del skip link. Sin `tabIndex={-1}` el salto mueve el scroll pero
      // no el foco en Safari, así que el teclado seguía atrapado en la barra de
      // navegación después de "saltar al contenido".
      tabIndex={-1}
      aria-label="Contenido principal"
      // La densidad se declara como atributo y `globals.css` la aplica sobre los
      // primitivos (`[data-slot]`). Antes era `[&_.container]:px-2`, y la clase
      // `.container` no se usa en ningún sitio del proyecto: el toggle sólo
      // cambiaba un `text-sm` global que casi todos los hijos sobrescriben.
      data-density={compact ? "compact" : "normal"}
      className="flex-1 overflow-auto"
    >
      {/* Primero de todo: es el centinela que decide si el cromo de arriba
          dibuja su borde. Tiene que ser el primer hijo del contenedor con
          scroll, no de la página, o mediría otra cosa. */}
      <ScrollEdgeSentinel />
      <h1 className="sr-only">{pageTitle}</h1>
      {children}
    </main>
  );
}
