import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AdjudicacionDetectada } from "@/components/pursuits/adjudicacion-detectada";
import type { Pursuit } from "@/hooks/use-pursuits";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const mutateAsync = vi.fn().mockResolvedValue({});
vi.mock("@/hooks/use-pursuits", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-pursuits")>();
  return { ...actual, useUpdatePursuit: () => ({ mutateAsync, isPending: false }) };
});

const base: Pursuit = {
  id: 1,
  organization_id: 7,
  licitacion_id: "lic-1",
  tender_title: "Servicio TI",
  tender_deadline: null,
  responsible_user_id: null,
  responsible_name: null,
  status: "submitted",
  decision: "go",
  decision_reason: "encaja",
  offer_price_eur: null,
  outcome: "pending",
  awarded_amount_eur: null,
  outcome_reason: null,
  identified_at: "2026-07-30T10:00:00Z",
  decision_at: null,
  submitted_at: "2026-08-01T10:00:00Z",
  closed_at: null,
  created_at: "2026-07-30T10:00:00Z",
  updated_at: "2026-07-30T10:00:00Z",
  version: 4,
  comments_count: 0,
  events: [],
  adjudicacion: {
    estado_licitacion: "ADJ",
    adjudicatarios: [
      {
        nombre: "Consultora Uno",
        nif: "B00000000",
        importe_adjudicado: 120000,
        fecha_adjudicacion: "2026-08-20",
        n_ofertas_recibidas: 3,
        lote_id: null,
      },
    ],
    importe_total: 120000,
    n_ofertas: 3,
    cierre_pendiente: true,
  },
} as Pursuit;

afterEach(() => mutateAsync.mockClear());

describe("AdjudicacionDetectada", () => {
  it("no renderiza nada sin adjudicación publicada", () => {
    const { container } = render(
      <AdjudicacionDetectada pursuit={{ ...base, adjudicacion: null } as Pursuit} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("muestra el adjudicatario publicado con su importe", () => {
    render(<AdjudicacionDetectada pursuit={base} />);
    expect(screen.getByText("Este expediente ya se adjudicó")).toBeInTheDocument();
    expect(screen.getByText("Consultora Uno")).toBeInTheDocument();
  });

  it("cierra como ganada mandando el importe adjudicado y la versión esperada", () => {
    render(<AdjudicacionDetectada pursuit={base} />);
    fireEvent.click(screen.getByRole("button", { name: /Cerrar como ganada/ }));

    expect(mutateAsync).toHaveBeenCalledTimes(1);
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({
      outcome: "won",
      awarded_amount_eur: 120000,
      expected_version: 4,
    });
  });

  it("no manda el importe del contrato al cerrar como perdida", () => {
    render(<AdjudicacionDetectada pursuit={base} />);
    fireEvent.click(screen.getByRole("button", { name: /Cerrar como perdida/ }));

    const payload = mutateAsync.mock.calls[0][0];
    expect(payload.outcome).toBe("lost");
    expect(payload).not.toHaveProperty("awarded_amount_eur");
  });

  it("sin oferta presentada explica el bloqueo y ofrece retirar", () => {
    render(<AdjudicacionDetectada pursuit={{ ...base, status: "qualifying" } as Pursuit} />);

    expect(screen.queryByRole("button", { name: /Cerrar como ganada/ })).toBeNull();
    expect(screen.getByText(/Oferta presentada/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Marcar como retirada/ }));
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({ status: "withdrawn" });
  });

  it("sin propuesta del backend no preselecciona nada", () => {
    // `resultado_sugerido: null` es el caso previo a S2.1 —sin NIFs declarados,
    // o sin NIF publicado del adjudicatario— y la tarjeta se comporta igual.
    render(<AdjudicacionDetectada pursuit={base} />);
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.getByText(/el sistema no sabe cuál de estas empresas sois/)).toBeInTheDocument();
  });

  describe("con resultado sugerido por NIF (S2.1)", () => {
    const conPropuesta = (resultado_sugerido: "won" | "lost") =>
      ({
        ...base,
        adjudicacion: { ...base.adjudicacion!, resultado_sugerido },
      }) as Pursuit;

    it("preselecciona la propuesta sin cerrar la oportunidad", () => {
      render(<AdjudicacionDetectada pursuit={conPropuesta("won")} />);

      expect(screen.getByRole("radio", { name: "La ganamos" })).toBeChecked();
      expect(screen.getByRole("radio", { name: "La perdimos" })).not.toBeChecked();
      // Preseleccionar no es cerrar: nada se manda hasta que alguien confirma.
      expect(mutateAsync).not.toHaveBeenCalled();
    });

    it("preselecciona también «perdida» cuando es lo que dice el NIF", () => {
      render(<AdjudicacionDetectada pursuit={conPropuesta("lost")} />);
      expect(screen.getByRole("radio", { name: "La perdimos" })).toBeChecked();
      expect(screen.getByRole("button", { name: /Confirmar como perdida/ })).toBeInTheDocument();
    });

    it("confirmar acepta la propuesta y cierra con ella", () => {
      render(<AdjudicacionDetectada pursuit={conPropuesta("won")} />);
      fireEvent.click(screen.getByRole("button", { name: /Confirmar como ganada/ }));

      expect(mutateAsync).toHaveBeenCalledTimes(1);
      expect(mutateAsync.mock.calls[0][0]).toMatchObject({
        outcome: "won",
        awarded_amount_eur: 120000,
        expected_version: 4,
      });
    });

    it("la persona puede contradecir la propuesta antes de confirmar", () => {
      render(<AdjudicacionDetectada pursuit={conPropuesta("won")} />);
      fireEvent.click(screen.getByRole("radio", { name: "La perdimos" }));

      expect(screen.getByRole("radio", { name: "La perdimos" })).toBeChecked();
      fireEvent.click(screen.getByRole("button", { name: /Confirmar como perdida/ }));

      const payload = mutateAsync.mock.calls[0][0];
      expect(payload.outcome).toBe("lost");
      expect(payload).not.toHaveProperty("awarded_amount_eur");
    });

    it("no arrastra la elección de una oportunidad a la siguiente", () => {
      // La ruta reutiliza el componente al saltar de ficha en ficha: heredar la
      // elección preseleccionaría un resultado que nadie ha propuesto aquí.
      const { rerender } = render(<AdjudicacionDetectada pursuit={conPropuesta("won")} />);
      fireEvent.click(screen.getByRole("radio", { name: "La perdimos" }));

      rerender(
        <AdjudicacionDetectada pursuit={{ ...conPropuesta("won"), id: 2 } as Pursuit} />,
      );
      expect(screen.getByRole("radio", { name: "La ganamos" })).toBeChecked();
    });

    it("sin la oferta presentada la propuesta no se puede confirmar", () => {
      render(
        <AdjudicacionDetectada
          pursuit={{ ...conPropuesta("won"), status: "qualifying" } as Pursuit}
        />,
      );
      expect(screen.queryByRole("radio")).toBeNull();
      expect(screen.getByText(/Oferta presentada/)).toBeInTheDocument();
    });
  });

  it("en una oportunidad ya cerrada la adjudicación es sólo contexto", () => {
    render(
      <AdjudicacionDetectada
        pursuit={
          {
            ...base,
            status: "won",
            adjudicacion: { ...base.adjudicacion!, cierre_pendiente: false },
          } as Pursuit
        }
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/ya está cerrada/)).toBeInTheDocument();
  });
});
