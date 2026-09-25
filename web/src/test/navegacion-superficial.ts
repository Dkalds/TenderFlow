/**
 * Doble de `next/navigation` con la integración de historial de Next 16.
 *
 * En la app, Next parchea `history.replaceState` y `pushState` para que
 * `useSearchParams` y `usePathname` devuelvan la URL nueva sin pedir nada al
 * servidor (`next/dist/client/components/app-router.js`). jsdom no monta el App
 * Router, y un mock que devuelve unos `URLSearchParams` fijos no puede
 * demostrar que un cambio de URL llega de verdad a la pantalla. Este doble
 * reproduce esa integración —los hooks leen `window.location` y vuelven a
 * pintar cuando el historial cambia— y deja `push` y `replace` como espías,
 * para poder afirmar además que nadie navegó.
 *
 * Uso:
 *
 *   vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));
 *   import { irA, router } from "@/test/navegacion-superficial";
 *
 * `irA(url)` fija la URL antes de pintar; los espías se limpian con el
 * `vi.clearAllMocks()` de cada suite.
 */
import * as React from "react";
import { vi } from "vitest";

const oyentes = new Set<() => void>();
let parcheado = false;

function avisar(): void {
  for (const oyente of oyentes) oyente();
}

/** Lo mismo que hace Next: escrito el historial, los hooks se enteran. */
function parchearHistorial(): void {
  if (parcheado) return;
  parcheado = true;
  const replaceState = window.history.replaceState.bind(window.history);
  const pushState = window.history.pushState.bind(window.history);
  window.history.replaceState = (estado, sinUso, url) => {
    replaceState(estado, sinUso, url);
    avisar();
  };
  window.history.pushState = (estado, sinUso, url) => {
    pushState(estado, sinUso, url);
    avisar();
  };
  window.addEventListener("popstate", avisar);
}

function suscribir(oyente: () => void): () => void {
  parchearHistorial();
  oyentes.add(oyente);
  return () => {
    oyentes.delete(oyente);
  };
}

/** Espías del router: un cambio superficial de la URL no debe tocar ninguno. */
export const router = {
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
};

export function useRouter(): typeof router {
  return router;
}

export function useSearchParams(): URLSearchParams {
  const search = React.useSyncExternalStore(
    suscribir,
    () => window.location.search,
    () => "",
  );
  return React.useMemo(() => new URLSearchParams(search), [search]);
}

export function usePathname(): string {
  return React.useSyncExternalStore(
    suscribir,
    () => window.location.pathname,
    () => "/",
  );
}

/** Deja la URL en `url`. Se llama antes de pintar, sin nada montado. */
export function irA(url: string): void {
  window.history.replaceState(null, "", url);
}
