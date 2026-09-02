import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PursuitEditor } from "@/components/pursuits/pursuit-editor";
import type { Pursuit } from "@/hooks/use-pursuits";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const mutateAsync = vi.fn().mockResolvedValue({});
const membersRef = { current: [] as Array<{ user_id: number; display_name: string | null; email: string | null }> };

vi.mock("@/hooks/use-pursuits", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-pursuits")>();
  return { ...actual, useUpdatePursuit: () => ({ mutateAsync, isPending: false }) };
});
vi.mock("@/hooks/use-organization", () => ({
  useOrganizationMembers: () => ({ data: membersRef.current }),
}));

const basePursuit: Pursuit = {
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
  offer_price_eur: null,
  outcome: "pending",
  awarded_amount_eur: null,
  outcome_reason: null,
  identified_at: "2026-07-30T10:00:00Z",
  decision_at: null,
  submitted_at: null,
  closed_at: null,
  created_at: "2026-07-30T10:00:00Z",
  updated_at: "2026-07-30T10:00:00Z",
  version: 1,
  comments_count: 0,
};

afterEach(() => {
  mutateAsync.mockClear();
  membersRef.current = [];
});

describe("PursuitEditor responsible-person selector", () => {
  // El `Select` de Radix también renderiza un <select> nativo oculto (para
  // semántica de formulario) con un <option> por cada texto — `getByText`
  // sin más lo encuentra dos veces. Se restringe la búsqueda al <span>
  // visible del trigger para desambiguar.
  const trigger = (name: string) => screen.getByText(name, { selector: "span" });

  it("shows 'Sin asignar' when there is no responsible person", () => {
    membersRef.current = [{ user_id: 5, display_name: "Ana Gómez", email: "ana@example.test" }];
    render(<PursuitEditor pursuit={basePursuit} />);

    expect(trigger("Sin asignar")).toBeInTheDocument();
  });

  it("renders the member's display name instead of a raw numeric id", () => {
    membersRef.current = [{ user_id: 5, display_name: "Ana Gómez", email: "ana@example.test" }];
    render(<PursuitEditor pursuit={{ ...basePursuit, responsible_user_id: 5 }} />);

    expect(trigger("Ana Gómez")).toBeInTheDocument();
    expect(screen.queryByText("5", { selector: "span" })).not.toBeInTheDocument();
  });

  it("falls back to the email, then to 'Usuario {id}', when display_name is missing", () => {
    membersRef.current = [{ user_id: 9, display_name: null, email: "solo-correo@example.test" }];
    const { rerender } = render(<PursuitEditor pursuit={{ ...basePursuit, responsible_user_id: 9 }} />);
    expect(trigger("solo-correo@example.test")).toBeInTheDocument();

    membersRef.current = [{ user_id: 11, display_name: null, email: null }];
    rerender(<PursuitEditor pursuit={{ ...basePursuit, id: 2, version: 1, responsible_user_id: 11 }} />);
    expect(trigger("Usuario 11")).toBeInTheDocument();
  });

  it("submits the numeric responsible_user_id already set on the pursuit", async () => {
    membersRef.current = [{ user_id: 5, display_name: "Ana Gómez", email: "ana@example.test" }];
    render(<PursuitEditor pursuit={{ ...basePursuit, responsible_user_id: 5 }} />);

    fireEvent.click(screen.getByRole("button", { name: /Guardar cambios/ }));

    await vi.waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith(expect.objectContaining({ responsible_user_id: 5 })),
    );
  });
});
