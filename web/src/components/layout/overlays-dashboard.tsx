"use client";

/**
 * Overlays del dashboard, bajo demanda.
 *
 * La paleta (⌘K), el copiloto, la bandeja de comparación y la ayuda de atajos
 * están cerrados al entrar en cualquier pantalla, y aun así viajaban en el
 * First Load de todas: el copiloto con react-markdown y remark-gfm, la paleta
 * con cmdk. Aquí queda montado solo lo mínimo —la suscripción a su store— y
 * cada cuerpo se descarga la primera vez que hace falta.
 *
 * Los atajos no viven aquí sino en `useKeyboardShortcuts` (`DashboardShell`),
 * que solo cambia el store: ⌘K y «?» funcionan antes de que exista la paleta o
 * la ayuda, y la abren a la primera. Las APIs de apertura (`useUiStore`,
 * `useBandejaComparacion`) no cambian.
 *
 * `ssr: false` en todos: ninguno pinta nada en el HTML del servidor, porque
 * todos arrancan cerrados.
 */

import * as React from "react";
import dynamic from "next/dynamic";
import { useBandejaComparacion } from "@/hooks/use-comparacion";
import { useUiStore } from "@/lib/ui-store";

/**
 * La primera apertura de la paleta, mientras llega su código: el mismo marco,
 * vacío. Sin animación, igual que la paleta (se abre con el teclado, cientos
 * de veces al día), y con el fondo que la cierra como en la de verdad.
 */
function PaletaCargando() {
  const cerrar = useUiStore((s) => s.setCommandOpen);
  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center p-4 pt-[12vh] sm:pt-[18vh]"
      role="dialog"
      aria-modal="true"
      aria-label="Paleta de comandos"
      aria-busy="true"
    >
      <button
        type="button"
        aria-label="Cerrar paleta de comandos"
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={() => cerrar(false)}
      />
      <div className="tf-glass-strong border-border/70 text-muted-foreground relative z-10 flex h-12 w-full max-w-xl items-center rounded-xl border px-3 text-sm shadow-2xl">
        Cargando…
      </div>
    </div>
  );
}

const CommandPalette = dynamic(() => import("@/components/command-palette").then((modulo) => modulo.CommandPalette), {
  ssr: false,
  loading: PaletaCargando,
});
const GlobalCopilot = dynamic(() => import("@/components/copilot-panel").then((modulo) => modulo.GlobalCopilot), {
  ssr: false,
});
const BandejaComparacion = dynamic(
  () => import("@/components/pliego/comparacion-bandeja").then((modulo) => modulo.BandejaComparacion),
  { ssr: false },
);
const KeyboardHelp = dynamic(() => import("@/components/keyboard-help").then((modulo) => modulo.KeyboardHelp), {
  ssr: false,
});

/**
 * `true` desde la primera vez que `abierto` lo es, y ya para siempre.
 *
 * El copiloto y la ayuda son un Sheet y un Dialog: tienen que seguir montados
 * al cerrarse para que se vea su animación de salida. Y el copiloto guarda la
 * conversación en su estado, así que desmontarlo al cerrar la borraría — antes
 * no pasaba porque estaba montado siempre.
 */
function useAbiertoAlgunaVez(abierto: boolean): boolean {
  const [visto, setVisto] = React.useState(abierto);
  if (abierto && !visto) setVisto(true);
  return visto || abierto;
}

/** Ejecuta `fn` cuando el navegador esté ocioso; devuelve cómo cancelarlo. */
function alQuedarOcioso(fn: () => void): () => void {
  if (typeof window.requestIdleCallback === "function") {
    const id = window.requestIdleCallback(fn, { timeout: 10_000 });
    return () => window.cancelIdleCallback(id);
  }
  // Safari no tiene `requestIdleCallback`: un margen fijo tras la carga.
  const id = window.setTimeout(fn, 3_000);
  return () => window.clearTimeout(id);
}

function PaletaDiferida() {
  const abierta = useUiStore((s) => s.commandOpen);
  // La paleta es la entrada de ⌘K y del buscador de la barra de ámbito: se
  // adelanta en cuanto el navegador queda ocioso, para que la primera apertura
  // no espere a la red. Llega después de pintar, así que no cuenta en el First
  // Load. Si falla, se reintenta al abrirla.
  React.useEffect(() => alQuedarOcioso(() => void import("@/components/command-palette").catch(() => undefined)), []);
  // Solo mientras está abierta: la paleta se monta limpia en cada apertura
  // (sin búsqueda previa ni efecto de reseteo) y no tiene salida animada.
  return abierta ? <CommandPalette /> : null;
}

function CopilotoDiferido() {
  const abierto = useUiStore((s) => s.copilotOpen);
  const visto = useAbiertoAlgunaVez(abierto);
  return visto ? <GlobalCopilot /> : null;
}

/** F2.8 — la bandeja sigue a mano al cambiar de pantalla mientras tenga algo. */
function BandejaDiferida() {
  const conExpedientes = useBandejaComparacion((s) => s.items.length > 0);
  return conExpedientes ? <BandejaComparacion /> : null;
}

function AyudaAtajosDiferida() {
  const abierta = useUiStore((s) => s.shortcutsHelpOpen);
  const vista = useAbiertoAlgunaVez(abierta);
  return vista ? <KeyboardHelp /> : null;
}

export function OverlaysDashboard() {
  return (
    <>
      <PaletaDiferida />
      <CopilotoDiferido />
      <BandejaDiferida />
      <AyudaAtajosDiferida />
    </>
  );
}
