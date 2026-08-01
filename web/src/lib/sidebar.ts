import { create } from "zustand";
import { getJSON, setJSON } from "@/lib/storage";

interface SidebarState {
  collapsed: boolean;
  toggleCollapsed: () => void;
}

/**
 * Estado de colapso de la sidebar, persistido.
 *
 * Mismo patrón que `lib/density.ts`: el store arranca siempre en el valor de
 * servidor y se sincroniza desde `localStorage` tras montar, para no romper la
 * hidratación. Antes era un `useState` local, así que era la única preferencia
 * de chrome que se perdía al recargar — tema y densidad sí persistían.
 */
export const useSidebar = create<SidebarState>((set) => ({
  collapsed: false,
  toggleCollapsed: () =>
    set((s) => {
      const next = !s.collapsed;
      setJSON("sidebar", next ? "collapsed" : "expanded");
      return { collapsed: next };
    }),
}));

/** Llamar una vez en un `useEffect` de cliente para sincronizar la preferencia. */
export function initSidebar() {
  if (getJSON<string>("sidebar", "expanded") === "collapsed") {
    useSidebar.setState({ collapsed: true });
  }
}
