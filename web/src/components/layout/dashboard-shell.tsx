"use client";

import { cn } from "@/lib/utils";
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
      className={cn(
        "flex-1 overflow-auto",
        compact && "text-sm [&_.container]:px-2 [&_.container]:py-3",
      )}
    >
      {children}
    </main>
  );
}
