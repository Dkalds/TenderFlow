/**
 * Overlays del dashboard bajo demanda (`overlays-dashboard.tsx`).
 *
 * Se fija lo que justifica el módulo y lo que no podía romperse por el camino:
 * al entrar no se descarga ninguno de los cuatro; ⌘K, «?» y los stores los
 * siguen abriendo a la primera, y la bandeja aparece y desaparece con su store.
 *
 * Cada overlay se dobla por un componente mínimo cuya factoría anota que se
 * descargó: la factoría corre la primera vez que algo importa el módulo. Cada
 * test monta módulos nuevos (`vi.resetModules`) y registra dobles nuevos
 * (`vi.doMock`): lo que se mide es qué se importa, y la caché de un test no
 * puede contaminar al siguiente. `resetModules` solo no basta, porque no
 * reinicia el registro de mocks: con `vi.mock` la factoría correría una sola
 * vez por fichero y el resultado dependería del orden de los tests.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

const { descargados, ociosas } = vi.hoisted(() => ({
  descargados: new Set<string>(),
  ociosas: [] as Array<() => void>,
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

function doblarOverlays() {
  vi.doMock("@/components/command-palette", () => {
    descargados.add("paleta");
    return { CommandPalette: () => <p>paleta de comandos</p> };
  });
  vi.doMock("@/components/keyboard-help", async () => {
    descargados.add("ayuda");
    const { useUiStore } = await import("@/lib/ui-store");
    return {
      KeyboardHelp: () => <p>ayuda {useUiStore((s) => s.shortcutsHelpOpen) ? "abierta" : "cerrada"}</p>,
    };
  });
  vi.doMock("@/components/copilot-panel", async () => {
    descargados.add("copiloto");
    const { useUiStore } = await import("@/lib/ui-store");
    return {
      GlobalCopilot: () => <p>copiloto {useUiStore((s) => s.copilotOpen) ? "abierto" : "cerrado"}</p>,
    };
  });
  vi.doMock("@/components/pliego/comparacion-bandeja", () => {
    descargados.add("bandeja");
    return { BandejaComparacion: () => <p>bandeja de comparación</p> };
  });
}

/** Monta el dashboard con los atajos de verdad y módulos recién importados. */
async function montar() {
  vi.resetModules();
  doblarOverlays();
  descargados.clear();
  const { OverlaysDashboard } = await import("@/components/layout/overlays-dashboard");
  const { useKeyboardShortcuts } = await import("@/hooks/use-keyboard-shortcuts");
  const { useUiStore } = await import("@/lib/ui-store");
  const { useBandejaComparacion } = await import("@/hooks/use-comparacion");

  function Dashboard() {
    useKeyboardShortcuts();
    return <OverlaysDashboard />;
  }
  render(<Dashboard />);
  return { useUiStore, useBandejaComparacion };
}

const DESCARGA = { timeout: 15_000 };

beforeEach(() => {
  ociosas.length = 0;
  // La precarga de la paleta espera a que el navegador esté ocioso: aquí lo
  // decide el test.
  vi.stubGlobal("requestIdleCallback", (cb: () => void) => ociosas.push(cb));
  vi.stubGlobal("cancelIdleCallback", () => {});
});

afterEach(() => {
  // Desmontar antes de devolver los globales: el efecto de la paleta cancela
  // su espera ociosa con el `cancelIdleCallback` doblado, que jsdom no tiene.
  cleanup();
  vi.unstubAllGlobals();
});

// Cada test importa módulos nuevos, y en una máquina cargada el primer import
// (transformar el árbol) pasa de los 5 s por defecto.
describe("OverlaysDashboard", { timeout: 30_000 }, () => {
  it("al entrar no descarga ni pinta ninguno de los cuatro", async () => {
    await montar();

    expect([...descargados]).toEqual([]);
    expect(screen.queryByText(/paleta|ayuda|copiloto|bandeja/)).toBeNull();
  });

  it("⌘K abre la paleta a la primera: marco mínimo mientras llega, y la paleta después", async () => {
    const { useUiStore } = await montar();

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });

    // Todavía sin el código de la paleta: el mismo marco, vacío.
    expect(screen.getByRole("dialog", { name: "Paleta de comandos" })).toHaveAttribute("aria-busy", "true");
    expect(await screen.findByText("paleta de comandos", {}, DESCARGA)).toBeInTheDocument();
    expect(descargados.has("paleta")).toBe(true);

    // ⌘K otra vez la cierra: la paleta se desmonta y se monta limpia en cada apertura.
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(useUiStore.getState().commandOpen).toBe(false);
    expect(screen.queryByText("paleta de comandos")).toBeNull();
  });

  it("el fondo del marco de carga cierra la paleta, como el de la paleta", async () => {
    const { useUiStore } = await montar();

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    fireEvent.click(screen.getByRole("button", { name: "Cerrar paleta de comandos" }));

    expect(useUiStore.getState().commandOpen).toBe(false);
    expect(screen.queryByRole("dialog", { name: "Paleta de comandos" })).toBeNull();
    // La descarga que empezó con ⌘K sigue en vuelo: que acabe aquí y no anote
    // nada en el test siguiente.
    await vi.dynamicImportSettled();
  });

  it("con el navegador ocioso adelanta la descarga de la paleta sin abrirla", async () => {
    await montar();
    expect(ociosas).toHaveLength(1);
    expect(descargados.has("paleta")).toBe(false);

    act(() => ociosas[0]());

    await vi.waitFor(() => expect(descargados.has("paleta")).toBe(true), DESCARGA);
    expect(screen.queryByText("paleta de comandos")).toBeNull();
  });

  it("«?» abre la ayuda, que sigue montada al cerrarse para animar la salida", async () => {
    await montar();

    fireEvent.keyDown(window, { key: "?" });
    expect(await screen.findByText("ayuda abierta", {}, DESCARGA)).toBeInTheDocument();
    expect(descargados.has("ayuda")).toBe(true);

    fireEvent.keyDown(window, { key: "?" });
    expect(screen.getByText("ayuda cerrada")).toBeInTheDocument();
  });

  it("el copiloto se descarga al abrirse y no se desmonta al cerrarlo (conserva la conversación)", async () => {
    const { useUiStore } = await montar();

    act(() => useUiStore.getState().openCopilot("¿Qué vence esta semana?"));
    expect(await screen.findByText("copiloto abierto", {}, DESCARGA)).toBeInTheDocument();
    expect(descargados.has("copiloto")).toBe(true);

    act(() => useUiStore.getState().setCopilotOpen(false));
    expect(screen.getByText("copiloto cerrado")).toBeInTheDocument();
  });

  it("la bandeja aparece con su primer expediente y se va al vaciarla", async () => {
    const { useBandejaComparacion } = await montar();
    expect(descargados.has("bandeja")).toBe(false);

    act(() => {
      useBandejaComparacion.getState().alternar({ id: "EXP-1", titulo: "Mantenimiento SAP" });
    });
    expect(await screen.findByText("bandeja de comparación", {}, DESCARGA)).toBeInTheDocument();
    expect(descargados.has("bandeja")).toBe(true);

    act(() => useBandejaComparacion.getState().vaciar());
    expect(screen.queryByText("bandeja de comparación")).toBeNull();
  });
});
