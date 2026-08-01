"use client";

import * as React from "react";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { NUMBER_SHORTCUTS } from "@/hooks/use-keyboard-shortcuts";
import { useUiStore } from "@/lib/ui-store";

interface ShortcutRow {
  keys: string[];
  description: string;
}

const GENERAL_SHORTCUTS: ShortcutRow[] = [
  { keys: ["Ctrl", "K"], description: "Abrir la paleta de comandos" },
  { keys: ["/"], description: "Ir al buscador de la página" },
  { keys: ["Esc"], description: "Cerrar el panel abierto" },
  { keys: ["?"], description: "Abrir esta ayuda" },
];

function Keys({ keys }: { keys: string[] }) {
  return (
    <span className="flex shrink-0 items-center gap-1">
      {keys.map((key, index) => (
        <React.Fragment key={key}>
          {index > 0 && <span className="text-[10px] text-muted-foreground">+</span>}
          <kbd className="rounded border border-border/70 bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground">
            {key}
          </kbd>
        </React.Fragment>
      ))}
    </span>
  );
}

function Group({ title, rows }: { title: string; rows: ShortcutRow[] }) {
  return (
    <section className="space-y-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{title}</h3>
      <ul className="space-y-1">
        {rows.map((row) => (
          <li key={row.description} className="flex items-center justify-between gap-4 text-sm">
            <span className="min-w-0 truncate text-muted-foreground">{row.description}</span>
            <Keys keys={row.keys} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Overlay de ayuda de atajos, abierto con `?`.
 *
 * Los atajos existían pero eran indescubribles: sólo ⌘K estaba anunciado, en el
 * botón de búsqueda del TopNav. La lista de navegación se deriva de
 * `NUMBER_SHORTCUTS` para que no pueda desincronizarse del hook que la
 * implementa.
 */
export function KeyboardHelp() {
  const open = useUiStore((s) => s.shortcutsHelpOpen);
  const setOpen = useUiStore((s) => s.setShortcutsHelpOpen);

  const navigation: ShortcutRow[] = NUMBER_SHORTCUTS.map((shortcut) => ({
    keys: [shortcut.key],
    description: `Ir a ${shortcut.label}`,
  }));

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="w-full max-w-md p-6">
        <DialogTitle>Atajos de teclado</DialogTitle>
        <DialogDescription className="mt-1">
          Los atajos de una sola tecla no actúan mientras escribís en un campo o navegás dentro de un
          menú.
        </DialogDescription>
        <div className="mt-5 space-y-5">
          <Group title="General" rows={GENERAL_SHORTCUTS} />
          <Group title="Navegación" rows={navigation} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
