"use client";

const SHORTCUTS = [
  { key: "J K", label: "navegar" },
  { key: "S", label: "seguir" },
  { key: "X", label: "descartar" },
  { key: "⏎", label: "abrir" },
];

/** Pie de la consola: qué se está viendo y con qué teclas se recorre. */
export function RadarPie({ statusLine }: { statusLine: string }) {
  return (
    <div className="flex h-[34px] min-w-0 flex-none items-center gap-3.5 border-t border-border/70 bg-card/60 px-3 text-[11px] text-muted-foreground md:px-3.5">
      <span className="tf-tnum truncate">{statusLine}</span>
      <span className="hidden text-muted-foreground/60 lg:inline">
        · top 24 del mercado abierto por potencial comercial
      </span>
      <div className="flex-1" />
      {SHORTCUTS.map((shortcut) => (
        <span key={shortcut.key} className="hidden items-center gap-1.5 md:inline-flex">
          <span className="rounded border border-border/70 px-1 py-0.5 font-mono text-[9px] font-medium">
            {shortcut.key}
          </span>
          {shortcut.label}
        </span>
      ))}
    </div>
  );
}
