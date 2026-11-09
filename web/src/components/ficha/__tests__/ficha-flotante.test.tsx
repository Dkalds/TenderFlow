/**
 * CU-02 — la ficha flotante (`ficha-flotante.tsx`): con `?ver=` pinta la ficha
 * junto a la pantalla actual sin taparla con un velo, pulsar fuera no la cierra
 * (la lista de debajo sigue viva) y la X la cierra quitando `ver` de la URL.
 * Desde `xl` va anclada como columna del marco (sin diálogo) y cierra con Esc.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { withNuqsTestingAdapter, type UrlUpdateEvent } from "nuqs/adapters/testing";

const { push, licitacion } = vi.hoisted(() => ({
  push: vi.fn(),
  licitacion: { estado: { data: undefined as unknown, error: null as unknown } },
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/hooks/use-licitacion", () => ({
  useLicitacion: () => ({ ...licitacion.estado, refetch: vi.fn() }),
}));
vi.mock("@/components/detail-inspector", () => ({
  DetailInspector: ({
    licitacion: l,
    onClose,
    onExpandir,
  }: {
    licitacion: { titulo: string };
    onClose: () => void;
    onExpandir: () => void;
  }) => (
    <div>
      <h2>{l.titulo}</h2>
      <button onClick={onClose}>Cerrar ficha</button>
      <button onClick={onExpandir}>Abrir la ficha completa</button>
    </div>
  ),
}));

import { FichaFlotante } from "../ficha-flotante";

function montar() {
  const onUrlUpdate = vi.fn<(evento: UrlUpdateEvent) => void>();
  render(
    <>
      <button>Otra licitación</button>
      <input aria-label="Buscar" />
      <FichaFlotante />
    </>,
    { wrapper: withNuqsTestingAdapter({ searchParams: "?ver=EXP-1", onUrlUpdate }) },
  );
  return onUrlUpdate;
}

afterEach(() => {
  cleanup();
  push.mockReset();
  licitacion.estado = { data: undefined, error: null };
});

describe("FichaFlotante", () => {
  it("pinta la ficha sin velo y pulsar fuera no la cierra", async () => {
    licitacion.estado = { data: { id_externo: "EXP-1", titulo: "Mantenimiento SAP" }, error: null };
    const onUrlUpdate = montar();

    expect(screen.getByRole("heading", { name: "Mantenimiento SAP" })).toBeInTheDocument();
    // Sin velo: lo que hay debajo sigue accesible y pulsable.
    expect(screen.getByRole("button", { name: "Otra licitación" })).toBeVisible();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Otra licitación" }));
    expect(screen.getByRole("dialog", { name: "Ficha de la licitación" })).toBeInTheDocument();
    // nuqs escribe la URL en diferido: se le da tiempo antes de afirmar que no la tocó.
    await new Promise((resolver) => setTimeout(resolver, 100));
    expect(onUrlUpdate).not.toHaveBeenCalled();
  });

  it("la X quita `ver` de la URL, y «Ficha completa» lleva a /detalle", async () => {
    licitacion.estado = { data: { id_externo: "EXP-1", titulo: "Mantenimiento SAP" }, error: null };
    const onUrlUpdate = montar();

    fireEvent.click(screen.getByRole("button", { name: "Abrir la ficha completa" }));
    expect(push).toHaveBeenCalledWith("/detalle?lic=EXP-1&ficha=completa");

    fireEvent.click(screen.getByRole("button", { name: "Cerrar ficha" }));
    await vi.waitFor(() => expect(onUrlUpdate).toHaveBeenCalledOnce());
    expect(onUrlUpdate.mock.calls[0][0].searchParams.get("ver")).toBeNull();
  });

  it("si la ficha no carga, lo dice con su reintento", () => {
    licitacion.estado = { data: undefined, error: new Error("boom") };
    montar();

    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo abrir la ficha");
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});

describe("FichaFlotante anclada (≥ xl)", () => {
  // jsdom no evalúa media queries y el stub de `src/test/setup.ts` responde «no
  // match» a todo, que aquí es la franja del `Sheet`. Pantalla de 1440 px: casan
  // `md` y `xl`, y la ficha se ancla.
  let original: typeof window.matchMedia;
  beforeEach(() => {
    original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  });
  afterEach(() => {
    window.matchMedia = original;
  });

  it("es una columna del marco, no un panel modal encima: sin diálogo", () => {
    licitacion.estado = { data: { id_externo: "EXP-1", titulo: "Mantenimiento SAP" }, error: null };
    montar();

    expect(screen.getByRole("heading", { name: "Mantenimiento SAP" })).toBeInTheDocument();
    // Ni `Sheet` ni `Dialog`: lo que hay debajo no queda tapado ni inerte.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Otra licitación" })).toBeVisible();
  });

  it("Esc la cierra quitando `ver` de la URL", async () => {
    licitacion.estado = { data: { id_externo: "EXP-1", titulo: "Mantenimiento SAP" }, error: null };
    const onUrlUpdate = montar();

    fireEvent.keyDown(window, { key: "Escape" });

    await vi.waitFor(() => expect(onUrlUpdate).toHaveBeenCalledOnce());
    expect(onUrlUpdate.mock.calls[0][0].searchParams.get("ver")).toBeNull();
  });

  it("Esc dentro de un campo de texto no la cierra", async () => {
    licitacion.estado = { data: { id_externo: "EXP-1", titulo: "Mantenimiento SAP" }, error: null };
    const onUrlUpdate = montar();
    const campo = screen.getByRole("textbox", { name: "Buscar" });

    fireEvent.keyDown(campo, { key: "Escape" });

    await new Promise((resolver) => setTimeout(resolver, 100));
    expect(onUrlUpdate).not.toHaveBeenCalled();
  });
});
