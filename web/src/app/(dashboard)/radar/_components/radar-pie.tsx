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
    <div className="flex h-[34px] min-w-0 flex-none items-center gap-3.5 border-t border-border/70 bg-card px-3 text-tf-micro text-muted-foreground md:px-3.5">
      <span className="tf-tnum truncate">{statusLine}</span>
      {/* Qué lista es: las 24 abiertas que mejor puntúan con tu perfil, no
          todas las abiertas. */}
      <span className="hidden lg:inline">· las 24 abiertas que mejor encajan con tu perfil</span>
      <div className="flex-1" />
      {SHORTCUTS.map((shortcut) => (
        <span key={shortcut.key} className="hidden items-center gap-1.5 md:inline-flex">
          <kbd className="rounded-sm border border-border/70 px-1 font-mono text-tf-micro font-medium">
            {shortcut.key}
          </kbd>
          {shortcut.label}
        </span>
      ))}
    </div>
  );
}
