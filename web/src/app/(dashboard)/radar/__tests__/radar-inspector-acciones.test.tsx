/**
 * F5.6 — silenciar y posponer desde el inspector del Radar.
 *
 * Fija que «Silenciar» pide 30 días, que «Posponer» manda el plazo elegido y
 * que ninguno de los dos se confunde con «Descartar», que no caduca.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

// «Seguir» es `SeguirBoton` (ADR-031 §C), que lee su estado de
// `useSeguimiento`. Aquí se prueba el aplazamiento, no el seguimiento: basta
// con un estado fijo y sin red.
const { alternar } = vi.hoisted(() => ({ alternar: vi.fn(() => true) }));
vi.mock("@/hooks/use-seguimiento", () => ({
  useSeguimiento: () => ({
    ids: new Set<string>(),
    sigue: () => false,
    alternar,
    seguir: vi.fn(),
    dejar: vi.fn(),
    isLoading: false,
    enVuelo: false,
  }),
}));

import { InspectorAcciones } from "../_components/radar-inspector-acciones";
import type { RadarTender } from "@/hooks/use-radar";

const TENDER = { id_externo: "ES-1", titulo: "Soporte SAP", url: null } as unknown as RadarTender;

function renderAcciones() {
  const handlers = { onDismiss: vi.fn(), onAplazar: vi.fn(), onFollowed: vi.fn(), onOpenPursuit: vi.fn() };
  render(<InspectorAcciones tender={TENDER} opening={false} {...handlers} />);
  return handlers;
}

afterEach(cleanup);

describe("InspectorAcciones — Más tarde", () => {
  it("silenciar pide 30 días y no descarta", () => {
    const h = renderAcciones();
    fireEvent.click(screen.getByRole("button", { name: /Silenciar 30 días/ }));
    expect(h.onAplazar).toHaveBeenCalledWith("silenciar", 30);
    expect(h.onDismiss).not.toHaveBeenCalled();
  });

  it("posponer manda el plazo elegido", () => {
    const h = renderAcciones();
    fireEvent.change(screen.getByLabelText("Recordar en"), { target: { value: "14" } });
    fireEvent.click(screen.getByRole("button", { name: /Posponer/ }));
    expect(h.onAplazar).toHaveBeenCalledWith("posponer", 14);
  });

  it("seguir pasa por el control único y avisa con el estado nuevo", () => {
    const h = renderAcciones();
    fireEvent.click(screen.getByRole("button", { name: "Seguir" }));
    expect(alternar).toHaveBeenCalledWith(["ES-1"]);
    expect(h.onFollowed).toHaveBeenCalledWith(true);
    expect(h.onAplazar).not.toHaveBeenCalled();
  });

  it("descartar sigue siendo su propio botón", () => {
    const h = renderAcciones();
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
    expect(h.onDismiss).toHaveBeenCalledTimes(1);
    expect(h.onAplazar).not.toHaveBeenCalled();
  });
});
