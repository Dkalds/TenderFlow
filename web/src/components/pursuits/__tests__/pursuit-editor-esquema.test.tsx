/**
 * Validación por esquema de la ficha de oportunidad (`PursuitUpdate`, S7.2).
 *
 * Antes, un importe ilegible («12k») viajaba como `null` y borraba en silencio
 * el que había; ahora se para y se explica bajo su campo.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PursuitEditor } from "@/components/pursuits/pursuit-editor";
import type { Pursuit } from "@/hooks/use-pursuits";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const mutateAsync = vi.fn().mockResolvedValue({});
vi.mock("@/hooks/use-pursuits", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-pursuits")>();
  return { ...actual, useUpdatePursuit: () => ({ mutateAsync, isPending: false }) };
});
vi.mock("@/hooks/use-organization", () => ({ useOrganizationMembers: () => ({ data: [] }) }));

const PURSUIT = {
  id: 1,
  organization_id: 7,
  licitacion_id: "lic-1",
  tender_title: "Servicio TI",
  tender_deadline: null,
  responsible_user_id: null,
  responsible_name: null,
  status: "identified",
  decision: "pending",
  decision_reason: null,
  offer_price_eur: 1000,
  outcome: "pending",
  awarded_amount_eur: null,
  outcome_reason: null,
  identified_at: "2026-07-30T10:00:00Z",
  decision_at: null,
  submitted_at: null,
  closed_at: null,
  created_at: "2026-07-30T10:00:00Z",
  updated_at: "2026-07-30T10:00:00Z",
  version: 3,
  comments_count: 0,
} as Pursuit;

afterEach(() => mutateAsync.mockClear());

describe("PursuitEditor — esquema", () => {
  it("un precio ilegible no se guarda y el error queda enlazado sin entrar en el nombre", async () => {
    render(<PursuitEditor pursuit={PURSUIT} />);
    const precio = screen.getByLabelText("Oferta prevista (€)");

    fireEvent.change(precio, { target: { value: "12k" } });
    fireEvent.click(screen.getByRole("button", { name: /Guardar cambios/ }));

    const error = await screen.findByText(/Escribe un importe en euros/);
    expect(error).toHaveAttribute("id", "pursuit-1-offer-price-error");
    expect(precio).toHaveAttribute("aria-invalid", "true");
    expect(precio).toHaveAttribute("aria-describedby", "pursuit-1-offer-price-error");
    // El nombre accesible (el que calcula el lector, no el texto del
    // `<label>`) sigue siendo solo la etiqueta: el error va `aria-hidden`.
    expect(screen.getByRole("textbox", { name: "Oferta prevista (€)" })).toBe(precio);
    expect(mutateAsync).not.toHaveBeenCalled();

    // Corregido, se revalida al escribir y se guarda.
    fireEvent.change(precio, { target: { value: "1250,5" } });
    await waitFor(() => expect(precio).not.toHaveAttribute("aria-invalid"));
    fireEvent.click(screen.getByRole("button", { name: /Guardar cambios/ }));
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({ offer_price_eur: 1250.5, awarded_amount_eur: null, expected_version: 3 }),
      ),
    );
  });

  it("un importe adjudicado negativo se para en cliente", async () => {
    // El importe adjudicado solo se edita con la oportunidad ganada: abierta,
    // el cierre va por «Registrar resultado».
    render(
      <PursuitEditor
        pursuit={{ ...PURSUIT, status: "won", decision: "go", decision_reason: "Encaja", outcome: "won" }}
      />,
    );

    fireEvent.change(screen.getByLabelText("Importe adjudicado (€)"), { target: { value: "-10" } });
    fireEvent.click(screen.getByRole("button", { name: /Guardar cambios/ }));

    expect(await screen.findByText(/Escribe un importe en euros/)).toHaveAttribute(
      "id",
      "pursuit-1-awarded-price-error",
    );
    expect(mutateAsync).not.toHaveBeenCalled();
  });
});
