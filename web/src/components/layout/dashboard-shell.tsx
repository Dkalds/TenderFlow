"use client";

import { usePathname } from "next/navigation";
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

export function DashboardShell({ children }: { children: React.ReactNode }) {
  useKeyboardShortcuts();
  const compact = useDensity((s) => s.compact);
  const pageTitle = usePageTitle();

  return (
    <main
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
      <h1 className="sr-only">{pageTitle}</h1>
      {children}
    </main>
  );
}
