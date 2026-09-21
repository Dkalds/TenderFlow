import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen, fireEvent, within } from "@testing-library/react";

/**
 * Cartera (Oportunidades → Cartera; hasta 2026-09-20 vivía en Mi Pipeline).
 *
 * Lo que fija este suite:
 *
 * 1. **Los cuatro KPIs salen de `GET /pursuits/cartera/resumen`**, no de sumar
 *    las filas. El fixture los hace incompatibles a propósito —siete contratos
 *    vivos y 4,2 M€ frente a dos filas y 100 mil €—, porque un total sumado en
 *    cliente sólo se distingue del bueno cuando los dos números no coinciden
 *    (ADR-014, invariante 1 de `web/AGENTS.md`). Mientras el resumen no ha
 *    llegado, esqueleto: un cero es una respuesta, y ahí no se sabe nada.
 * 2. **El inspector** enseña el contrato seleccionado con su cronología
 *    (`/cartera/{id}/eventos`), pide los eventos **del contrato elegido** y
 *    tiene sus tres estados: cargando, vacío y con eventos.
 * 3. **«Preparar renovación»** sigue igual: sólo donde no hay oportunidad de
 *    renovación (los que la tienen enlazan), pide el expediente de la
 *    relicitación, no deja mandar el del contrato vigente y llama a la mutación
 *    con el contrato correcto.
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

/** Estado mutable de las dos consultas nuevas, para moverlo por test. */
const servidor = vi.hoisted(() => ({
  resumen: {
    data: undefined as Record<string, number> | undefined,
    isPending: false,
  },
  eventos: {
    data: undefined as { fecha: string; tipo: string; descripcion: string; importe_delta_eur: number | null }[] | undefined,
    isPending: false,
    error: null as Error | null,
  },
  eventosPedidos: [] as (number | null)[],
}));

vi.mock("@/hooks/use-cartera", () => ({
  useCartera: () => ({ data: contratos, isPending: false, error: null, refetch: vi.fn() }),
  useCarteraResumen: () => servidor.resumen,
  useCarteraEventos: (carteraId: number | null) => {
    servidor.eventosPedidos.push(carteraId);
    return servidor.eventos;
  },
  usePrepararRenovacion: () => ({ mutate, isPending: false, error: null }),
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { formatCompactCurrency } from "@/lib/utils";
import Vista from "../_components/cartera-view";

function CarteraView() {
  return (
    <TooltipProvider>
      <Vista />
    </TooltipProvider>
  );
}

/** La celda entera de un KPI, para no confundir su cifra con la de la tabla. */
function kpi(label: string): HTMLElement {
  return screen.getByText(label).closest(".bg-card") as HTMLElement;
}

const RESUMEN = {
  organization_id: 1,
  contratos_vivos: 7,
  importe_en_ejecucion_eur: 4_200_000,
  vencen_6_meses: 3,
  vencen_6_meses_importe_eur: 900_000,
  sin_renovacion_preparada: 2,
};

beforeEach(() => {
  vi.clearAllMocks();
  servidor.resumen = { data: RESUMEN, isPending: false };
  servidor.eventos = { data: [], isPending: false, error: null };
  servidor.eventosPedidos = [];
});
afterEach(cleanup);

describe("CarteraView · franja de KPIs", () => {
  it("las cuatro cifras vienen del resumen del servidor, no de las dos filas", () => {
    render(<CarteraView />);

    // Sumando las filas saldrían 2 contratos y 100 mil €.
    expect(within(kpi("Contratos vivos")).getByText("7")).toBeInTheDocument();
    // La cadena esperada sale del mismo formateador y no de un literal: con el
    // literal «4,2 M€» el test pasaba en Windows y fallaba en el runner Linux de
    // CI, cuyo ICU espacia la notación compacta de otra forma. Lo que este test
    // fija es de dónde viene la cifra, no cómo se espacia.
    expect(
      within(kpi("Importe en ejecución")).getByText(formatCompactCurrency(4_200_000)),
    ).toBeInTheDocument();
    expect(within(kpi("Vencen en 6 meses")).getByText("3")).toBeInTheDocument();
    expect(within(kpi("Vencen en 6 meses")).getByText(/900 mil €/)).toBeInTheDocument();

    const sinRenovacion = kpi("Sin renovación preparada");
    expect(within(sinRenovacion).getByText("2")).toBeInTheDocument();
    expect(within(sinRenovacion).getByText("De los que vencen en 6 meses")).toBeInTheDocument();
  });

  it("mientras el resumen no ha llegado enseña esqueleto, no ceros", () => {
    servidor.resumen = { data: undefined, isPending: true };
    render(<CarteraView />);

    const celda = kpi("Contratos vivos");
    expect(within(celda).queryByText("0")).not.toBeInTheDocument();
    expect(celda.querySelector(".tf-shimmer")).not.toBeNull();
  });
});

describe("CarteraView · inspector", () => {
  it("al elegir un contrato enseña su detalle y pide su cronología", () => {
    servidor.eventos = {
      data: [
        { fecha: "2025-01-15", tipo: "formalizacion", descripcion: "Contrato formalizado", importe_delta_eur: null },
        { fecha: "2026-03-01", tipo: "modificacion", descripcion: "Ampliación de alcance", importe_delta_eur: 12000 },
      ],
      isPending: false,
      error: null,
    };
    render(<CarteraView />);

    // Sin selección, el inspector pide que se elija uno.
    const inspector = screen.getByRole("complementary", {
      name: "Detalle del contrato seleccionado",
    });
    expect(
      within(inspector).getByText(/Selecciona un contrato para ver su detalle/),
    ).toBeInTheDocument();
    // Sin contrato elegido, la cronología ni se monta: no hay petición.
    expect(servidor.eventosPedidos).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Ver detalle de Mantenimiento SAP" }));

    // Los eventos se piden del contrato elegido, no de la tabla entera.
    expect(servidor.eventosPedidos.at(-1)).toBe(11);
    expect(within(inspector).getByRole("heading", { name: "Mantenimiento SAP" })).toBeInTheDocument();
    expect(within(inspector).getByText("1 ene 2027")).toBeInTheDocument();
    expect(within(inspector).getByText("1 ene 2025")).toBeInTheDocument();
    expect(within(inspector).getByText("100 mil €")).toBeInTheDocument();
    expect(within(inspector).getByText("LIC-VIGENTE")).toBeInTheDocument();
    expect(within(inspector).getByText(/1 jul 2026/)).toBeInTheDocument();
    expect(within(inspector).getByText("Contrato formalizado")).toBeInTheDocument();
    expect(within(inspector).getByText("Ampliación de alcance")).toBeInTheDocument();
    expect(within(inspector).getByText(/\+12 mil €/)).toBeInTheDocument();
  });

  it("dice que la cronología está cargando y que está vacía, en vez de callar", () => {
    servidor.eventos = { data: undefined, isPending: true, error: null };
    const { rerender } = render(<CarteraView />);
    fireEvent.click(screen.getByRole("button", { name: "Ver detalle de Mantenimiento SAP" }));
    expect(
      screen.getByRole("status", { name: "Cargando la cronología del contrato" }),
    ).toBeInTheDocument();

    servidor.eventos = { data: [], isPending: false, error: null };
    rerender(<CarteraView />);
    expect(screen.getByText("Sin eventos registrados desde la adjudicación.")).toBeInTheDocument();
  });

  it("el contrato que ya tiene renovación la enlaza también desde el inspector", () => {
    render(<CarteraView />);
    fireEvent.click(screen.getByRole("button", { name: "Ver detalle de Soporte Oracle" }));

    const inspector = screen.getByRole("complementary", {
      name: "Detalle del contrato seleccionado",
    });
    expect(
      within(inspector).getByRole("link", { name: "Abrir la oportunidad de renovación" }),
    ).toHaveAttribute("href", "/oportunidades/99");
    // La acción de la fila no la sustituye el inspector: sigue ahí.
    expect(screen.getByRole("link", { name: "Ver oportunidad de renovación" })).toBeInTheDocument();
  });
});

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
