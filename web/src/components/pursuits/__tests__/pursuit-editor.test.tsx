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

    // Sin cambios no hay nada que guardar: se toca otro campo.
    fireEvent.change(screen.getByLabelText("Oferta prevista (€)"), { target: { value: "90000" } });
    fireEvent.click(screen.getByRole("button", { name: /Guardar cambios/ }));

    await vi.waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith(expect.objectContaining({ responsible_user_id: 5 })),
    );
  });
});

describe("PursuitEditor — solo lo que la fase admite", () => {
  it("guardar solo se activa con cambios", () => {
    render(<PursuitEditor pursuit={basePursuit} />);
    const guardar = screen.getByRole("button", { name: /Guardar cambios/ });
    expect(guardar).toBeDisabled();
    expect(screen.getByText("Sin cambios que guardar.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Oferta prevista (€)"), { target: { value: "90000" } });
    expect(guardar).toBeEnabled();
  });

  it("abierta, no ofrece campos de cierre ni un NO-GO que el backend rechaza", () => {
    render(<PursuitEditor pursuit={basePursuit} decisiones={["pending", "go"]} />);

    expect(screen.queryByLabelText("Importe adjudicado (€)")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Nota de cierre/)).not.toBeInTheDocument();
    // El `<select>` nativo que Radix monta para el formulario trae una opción
    // por cada una que se ofrece.
    expect(screen.queryByText("NO-GO", { selector: "option" })).not.toBeInTheDocument();
    expect(screen.getByText("GO", { selector: "option" })).toBeInTheDocument();
    expect(screen.getByText("El NO-GO se toma en la fase «Decisión».")).toBeInTheDocument();
  });

  it("no manda a cambiar la fase a un sitio que no la cambia", () => {
    render(<PursuitEditor pursuit={basePursuit} />);
    expect(screen.queryByText(/path de la cabecera/)).not.toBeInTheDocument();
    expect(screen.getByText(/La fase se cambia desde «Para salir de…», arriba/)).toBeInTheDocument();
  });

  it("con la oferta en marcha la decisión es GO y no se puede cambiar", () => {
    render(
      <PursuitEditor
        pursuit={{ ...basePursuit, status: "preparing", decision: "go", decision_reason: "Encaja" }}
        decisiones={["go"]}
      />,
    );
    expect(screen.getByRole("combobox", { name: /Decisión/ })).toBeDisabled();
    expect(screen.getByText(/la decisión es GO\. Para abandonarla, retírala\./)).toBeInTheDocument();
  });

  it("cerrada, enseña el resultado fijo y deja completar el cierre", () => {
    render(
      <PursuitEditor
        pursuit={{ ...basePursuit, status: "won", decision: "go", decision_reason: "Encaja", outcome: "won" }}
        decisiones={["go"]}
      />,
    );
    expect(screen.getByText("Ganada")).toBeInTheDocument();
    expect(screen.getByText("Una oportunidad cerrada ya no cambia de resultado.")).toBeInTheDocument();
    expect(screen.getByLabelText("Importe adjudicado (€)")).toBeInTheDocument();
    expect(screen.getByLabelText("Nota de cierre")).toBeInTheDocument();
  });
});
