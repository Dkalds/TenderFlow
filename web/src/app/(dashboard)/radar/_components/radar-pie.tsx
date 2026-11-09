"use client";

const SHORTCUTS = [
  { key: "J K", label: "navegar" },
  { key: "S", label: "seguir" },
  { key: "X", label: "descartar" },
  { key: "⏎", label: "abrir" },
];

/** Pie de la consola: qué se está viendo y con qué teclas se recorre. */
export function RadarPie({ statusLine, ranking = true }: { statusLine: string; ranking?: boolean }) {
  return (
    <div className="flex h-[34px] min-w-0 flex-none items-center gap-3.5 border-t border-divider bg-card px-3 text-tf-micro text-muted-foreground md:px-3.5">
      <span className="tf-tnum truncate">{statusLine}</span>
      {/* Qué lista es: el top del ranking (`limit=24`), no todas las abiertas.
          «Hasta»: el ámbito puede dejar menos, y decir «las 24» sobre 4 filas
          era falso. En Próximas no aplica: es otra bandeja, sin score. */}
      {ranking && (
        <span className="hidden lg:inline">· hasta 24 abiertas, las que mejor encajan con tu perfil</span>
      )}
      <div className="flex-1" />
      {SHORTCUTS.map((shortcut) => (
        <span key={shortcut.key} className="hidden items-center gap-1.5 md:inline-flex">
          <kbd className="rounded-sm border border-divider px-1 font-mono text-tf-micro font-medium">
            {shortcut.key}
          </kbd>
          {shortcut.label}
        </span>
      ))}
    </div>
  );
}
