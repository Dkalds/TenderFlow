"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUiStore } from "@/lib/ui-store";

/**
 * Destinos de los atajos numéricos, en el orden en que se pulsan.
 *
 * Antes apuntaban a las cinco páginas analíticas *legacy* y ninguno llevaba a
 * Radar ni a Oportunidades, los dos espacios que el producto declara primarios.
 * Se exporta para que el overlay de ayuda (`?`) documente exactamente lo que
 * hace el hook, en vez de mantener una lista paralela que driftea.
 */
export const NUMBER_SHORTCUTS: ReadonlyArray<{ key: string; href: string; label: string }> = [
  { key: "1", href: "/radar", label: "Radar" },
  { key: "2", href: "/oportunidades", label: "Oportunidades" },
  { key: "3", href: "/resumen", label: "Resumen" },
  { key: "4", href: "/detalle", label: "Detalle" },
  { key: "5", href: "/competidores", label: "Competidores" },
  { key: "6", href: "/investigador", label: "Investigador" },
];

/** Roles de widget que consumen las teclas por su cuenta (typeahead, edición…). */
const TYPING_ROLES =
  '[role="listbox"],[role="combobox"],[role="menu"],[role="dialog"],[role="grid"],[role="textbox"]';

/**
 * ¿El evento viene de un sitio donde el usuario está escribiendo o navegando
 * dentro de un widget?
 *
 * El guard original sólo excluía `HTMLInputElement`/`HTMLTextAreaElement`, así
 * que con el foco en un `contenteditable` o en un listbox de Radix (que hace
 * typeahead sobre las mismas teclas) pulsar "1" te sacaba de la página.
 */
function isTypingContext(target: EventTarget | null): boolean {
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return true;
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return target.closest(TYPING_ROLES) !== null;
}

export function useKeyboardShortcuts() {
  const router = useRouter();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Ctrl+K / Cmd+K opens the command palette from anywhere (even inputs).
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        useUiStore.getState().toggleCommand();
        return;
      }

      // Un modificador convierte el atajo en otra cosa (Alt+1 / Ctrl+1 cambian
      // de pestaña en el navegador): no lo interceptamos.
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      if (isTypingContext(e.target)) return;

      switch (e.key) {
        case "?":
          e.preventDefault();
          useUiStore.getState().toggleShortcutsHelp();
          return;
        case "/":
          e.preventDefault();
          document
            .querySelector<HTMLInputElement>("[data-search-input] input, input[data-search-input]")
            ?.focus();
          return;
        case "Escape":
          document.querySelector<HTMLButtonElement>("[data-close-panel]")?.click();
          return;
      }

      const shortcut = NUMBER_SHORTCUTS.find((item) => item.key === e.key);
      if (shortcut) router.push(shortcut.href);
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [router]);
}
