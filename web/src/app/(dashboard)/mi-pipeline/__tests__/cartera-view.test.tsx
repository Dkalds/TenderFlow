import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

/**
 * F4.3 — «Preparar renovación» en la vista Cartera.
 *
 * Se fija: el botón solo aparece en contratos sin oportunidad de renovación
 * (los que ya la tienen enlazan), pide el expediente de la relicitación, no
 * deja mandar el del contrato vigente y llama a la mutación con el contrato
 * correcto.
 */

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  registrarEvento: vi.fn(),
}));
const toastSuccess = vi.fn();
vi.mock("sonner", () => ({ toast: { success: (...a: unknown[]) => toastSuccess(...a), error: vi.fn() } }));

const mutate = vi.fn();
const contratos = [
  {
    id: 11,
    organization_id: 1,
    pursuit_id: 7,
    licitacion_id: "LIC-VIGENTE",
    titulo: "Mantenimiento SAP",
    organo_contratacion: "Ayuntamiento",
    tecnologia: "SAP",
    cpv: null,
    fecha_inicio: "2025-01-01",
    fecha_fin_efectiva: "2027-01-01",
    fecha_fin_origen: "publicada",
    importe_adjudicado: 100000,
    prorrogas_aplicadas: 0,
    renovacion_pursuit_id: null,
    meses_restantes: 4,
    relicitacion_desde: "2026-07-01",
    relicitacion_hasta: "2026-10-01",
  },
  {
    id: 12,
    organization_id: 1,
    pursuit_id: 8,
    licitacion_id: "LIC-OTRO",
    titulo: "Soporte Oracle",
    organo_contratacion: "Diputación",
    tecnologia: "Oracle",
    cpv: null,
    fecha_inicio: null,
    fecha_fin_efectiva: null,
    fecha_fin_origen: null,
    importe_adjudicado: null,
    prorrogas_aplicadas: 0,
    renovacion_pursuit_id: 99,
    meses_restantes: null,
    relicitacion_desde: null,
    relicitacion_hasta: null,
  },
];
vi.mock("@/hooks/use-cartera", () => ({
  useCartera: () => ({ data: contratos, isLoading: false, error: null, refetch: vi.fn() }),
  usePrepararRenovacion: () => ({ mutate, isPending: false, error: null }),
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import Vista from "../_components/cartera-view";

function CarteraView() {
  return (
    <TooltipProvider>
      <Vista />
    </TooltipProvider>
  );
}

beforeEach(() => vi.clearAllMocks());

describe("CarteraView · preparar renovación", () => {
  it("solo ofrece el botón donde no hay renovación, y enlaza la que ya existe", () => {
    render(<CarteraView />);
    expect(screen.getAllByRole("button", { name: "Preparar renovación" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Ver oportunidad de renovación" })).toHaveAttribute(
      "href",
      "/oportunidades/99",
    );
  });

  it("pide el expediente de la relicitación y rechaza el vigente", () => {
    render(<CarteraView />);
    fireEvent.click(screen.getByRole("button", { name: "Preparar renovación" }));

    const campo = screen.getByLabelText("Expediente de la relicitación");
    const crear = screen.getByRole("button", { name: "Crear oportunidad" });
    expect(crear).toBeDisabled();

    fireEvent.change(campo, { target: { value: "LIC-VIGENTE" } });
    expect(screen.getByText(/Ese es el expediente del contrato vigente/)).toBeInTheDocument();
    expect(crear).toBeDisabled();

    fireEvent.change(campo, { target: { value: " LIC-NUEVA " } });
    fireEvent.click(crear);
    expect(mutate).toHaveBeenCalledWith(
      { carteraId: 11, licitacionId: "LIC-NUEVA" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );

    const { onSuccess } = mutate.mock.calls[0][1];
    onSuccess({ cartera_id: 11, renovacion_pursuit_id: 50, creada: false });
    expect(toastSuccess).toHaveBeenCalledWith("Este contrato ya tenía su oportunidad de renovación");
  });
});
