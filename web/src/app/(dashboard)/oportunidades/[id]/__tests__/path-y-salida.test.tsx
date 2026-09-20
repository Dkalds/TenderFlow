import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { Pursuit } from "@/hooks/use-pursuits";
import { PathFases } from "../_components/path-fases";
import { SalidaDeFase } from "../_components/salida-fase";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-pursuit-kit", () => ({
  usePursuitKit: () => ({ data: undefined }),
  resumenKit: () => ({ listos: 0, total: 0 }),
}));
vi.mock("@/hooks/use-pursuit-checklist", () => ({ usePursuitChecklist: () => ({ data: undefined }) }));

const mutate = vi.fn();
vi.mock("@/hooks/use-pursuits", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-pursuits")>();
  return { ...actual, useUpdatePursuit: () => ({ mutate, isPending: false }) };
});

const base = {
  id: 9,
  organization_id: 7,
  licitacion_id: "2026/0410",
  tender_title: "Plataforma de gestión documental",
  status: "go_no_go",
  decision: "pending",
  decision_reason: null,
  outcome: "pending",
  offer_price_eur: null,
  responsible_user_id: null,
  next_action: null,
  awarded_amount_eur: null,
  adjudicacion: null,
  version: 4,
} as unknown as Pursuit;

const en = (cambios: Partial<Pursuit>): Pursuit => ({ ...base, ...cambios }) as Pursuit;

describe("PathFases", () => {
  it("marca la fase actual como paso en curso", () => {
    render(<PathFases pursuit={en({ status: "preparing", decision: "go" })} />);
    const actual = screen.getAllByRole("listitem").find((li) => li.getAttribute("aria-current") === "step");
    expect(actual).toHaveTextContent("Preparando oferta");
  });

  it("cerrada, la última casilla nombra el resultado", () => {
    render(<PathFases pursuit={en({ status: "won", decision: "go", outcome: "won" })} />);
    const casillas = screen.getAllByRole("listitem");
    expect(casillas[casillas.length - 1]).toHaveTextContent("Ganada");
    expect(screen.queryByText("Cerrada")).not.toBeInTheDocument();
  });
});

describe("SalidaDeFase", () => {
  it("no deja empezar la oferta sin GO, y dice qué falta", () => {
    render(<SalidaDeFase pursuit={en({ status: "go_no_go" })} />);
    expect(screen.getByRole("button", { name: /Empezar la oferta/ })).toBeDisabled();
    expect(
      screen.getByText("Preparar o presentar una oferta exige la decisión GO."),
    ).toBeInTheDocument();
  });

  it("con el GO y su motivo, avanza con la versión que tenía", () => {
    mutate.mockClear();
    render(
      <SalidaDeFase
        pursuit={en({ status: "go_no_go", decision: "go", decision_reason: "Encaja con la práctica" })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Empezar la oferta/ }));
    expect(mutate).toHaveBeenCalledWith(
      { status: "preparing", expected_version: 4 },
      expect.anything(),
    );
  });

  // El diálogo se carga bajo demanda (`next/dynamic`), para no meter el
  // `Dialog` de Radix en el First Load de la ruta: por eso se espera.
  it("desde Presentada, la salida es registrar el resultado y abre el diálogo", async () => {
    render(<SalidaDeFase pursuit={en({ status: "submitted", decision: "go" })} />);
    fireEvent.click(screen.getByRole("button", { name: "Registrar resultado" }));
    expect(
      await screen.findByText("Cerrar la oportunidad", {}, { timeout: 5000 }),
    ).toBeInTheDocument();
  });
});
