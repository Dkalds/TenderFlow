/**
 * CU-02 — la ficha flotante (`ficha-flotante.tsx`): con `?ver=` pinta la ficha
 * sobre la pantalla actual sin taparla con un velo, pulsar fuera no la cierra
 * (la lista de debajo sigue viva) y la X la cierra quitando `ver` de la URL.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
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
