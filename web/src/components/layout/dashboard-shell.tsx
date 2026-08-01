"use client";

import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";
import { useDensity } from "@/lib/density";

export function DashboardShell({ children }: { children: React.ReactNode }) {
  useKeyboardShortcuts();
  const compact = useDensity((s) => s.compact);

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
      {children}
    </main>
  );
}
