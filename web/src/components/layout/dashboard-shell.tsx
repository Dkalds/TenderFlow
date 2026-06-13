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
