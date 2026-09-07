"use client";

import { useSyncExternalStore } from "react";
import { useTheme } from "next-themes";
import { Panel, PanelTitle, SectionTitle } from "@/components/console/panel";
import { Switch } from "@/components/ui/switch";
import { useDensity } from "@/lib/density";

/**
 * Apariencia — tema y densidad, en el sitio donde se buscan.
 *
 * Las dos existían y sólo se podían cambiar desde la paleta de comandos
 * (`Ctrl+K` → «tema»), que es un atajo para quien ya sabe que está ahí. Un
 * ajuste que sólo se encuentra con un atajo es un ajuste que la mayoría no
 * tiene.
 */

const TEMAS = [
  { valor: "light", etiqueta: "Claro" },
  { valor: "dark", etiqueta: "Oscuro" },
  { valor: "system", etiqueta: "El del sistema" },
] as const;

export default function AparienciaView() {
  const { theme, setTheme } = useTheme();
  const compact = useDensity((s) => s.compact);
  const toggleCompact = useDensity((s) => s.toggleCompact);

  // `next-themes` no sabe el tema hasta que monta: pintar un radio marcado en
  // servidor y otro distinto en cliente produce un salto visible y un aviso de
  // hidratación. `useSyncExternalStore` es el primitivo para exactamente esto —
  // un valor que en servidor es uno y en cliente otro— y evita el `setState`
  // dentro de un efecto que `react-hooks/set-state-in-effect` prohíbe.
  const montado = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );

  return (
    <div className="space-y-4">
      <Panel>
        <PanelTitle title="Tema" hint="Se aplica al instante y se recuerda en este navegador" />
        <fieldset className="flex flex-wrap gap-2" disabled={!montado}>
          <legend className="sr-only">Tema de la interfaz</legend>
          {TEMAS.map((opcion) => (
            <label
              key={opcion.valor}
              className="flex cursor-pointer items-center gap-2 rounded-md border border-border/60 px-3 py-1.5 text-[11.5px] has-[:checked]:border-primary/60 has-[:checked]:bg-primary/10"
            >
              <input
                type="radio"
                name="tema"
                value={opcion.valor}
                checked={montado ? theme === opcion.valor : false}
                onChange={() => setTheme(opcion.valor)}
                aria-label={opcion.etiqueta}
                className="size-3 accent-[var(--primary)]"
              />
              {opcion.etiqueta}
            </label>
          ))}
        </fieldset>
      </Panel>

      <Panel>
        <PanelTitle title="Densidad" hint="Filas más juntas en tablas y listados" />
        <div className="flex items-center justify-between gap-4">
          <div>
            <SectionTitle>Modo compacto</SectionTitle>
            <p className="text-[11px] leading-[1.5] text-muted-foreground">
              Reduce el alto de fila del Radar y de las tablas. Útil en pantallas pequeñas o
              cuando se comparan muchos expedientes a la vez.
            </p>
          </div>
          <Switch
            checked={compact}
            onCheckedChange={() => toggleCompact()}
            aria-label="Modo compacto"
          />
        </div>
      </Panel>
    </div>
  );
}
