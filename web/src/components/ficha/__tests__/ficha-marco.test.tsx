import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { MarcoDeLicitacion } from "@/lib/api-types";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import type { SistemaContratacion } from "@/lib/sistema-contratacion";

vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  organizacionResuelta: () => true,
}));

import { FichaMarco } from "@/components/ficha/ficha-marco";

function servir(respuesta: Partial<MarcoDeLicitacion>) {
  const fetchMock = vi.fn(() =>
    Promise.resolve(jsonResponse({ licitacion_id: "AM-1", sistema: "marco", identidad_conocida: true, ...respuesta })),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function montar(sistema: SistemaContratacion | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const licitacion = { id_externo: "AM-1", sistema_contratacion: sistema } as LicitacionDetail;
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <FichaMarco licitacion={licitacion} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const ADMITIDOS = [
  { nombre: "Mi Empresa SL", nif: "B11223344", lotes: ["1", "2"], es_tu_organizacion: true },
  { nombre: "Rival Uno SA", nif: "A28000001", lotes: ["1"], es_tu_organizacion: false },
];

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("FichaMarco", () => {
  it.each([null, "ninguno"] as const)("un expediente corriente (%s) no pinta nada ni pide nada", (sistema) => {
    const fetchMock = servir({});
    const { container } = montar(sistema);

    expect(container).toBeEmptyDOMElement();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("en un acuerdo marco dice cuántas empresas están admitidas y que la tuya es una", async () => {
    const fetchMock = servir({
      admitidos_total: 2,
      admitidos: ADMITIDOS,
      organizacion_admitida: true,
      vigencia: { fecha_fin: "2027-03-12", origen: "estimada_inicio", dias_restantes: 122 },
    });
    montar("marco");

    expect(await screen.findByText("2 empresas")).toBeInTheDocument();
    expect(callUrl(fetchMock.mock.calls[0])).toBe("/api/v1/licitaciones/AM-1/marco?organization_id=7");
    expect(screen.getByRole("heading", { name: "Acuerdo marco" })).toBeInTheDocument();
    expect(screen.getByText("Está admitida")).toBeInTheDocument();
    // La fecha calculada se rotula como estimada, igual que en Renovaciones.
    expect(screen.getByText(/^Hasta el /)).toBeInTheDocument();
    expect(screen.getByText("estimada")).toBeInTheDocument();
    expect(screen.getByText("Quedan 122 días")).toBeInTheDocument();
    expect(screen.getByText("Ver las 2 empresas admitidas")).toBeInTheDocument();
    expect(screen.getByText("Tu organización · Lotes 1, 2")).toBeInTheDocument();
  });

  it("los contratos basados van como sin dato, no como cero", async () => {
    servir({ admitidos_total: 2, admitidos: ADMITIDOS, organizacion_admitida: false });
    montar("marco");

    expect(await screen.findByText("No está entre los admitidos")).toBeInTheDocument();
    expect(screen.getByText(/no publican de qué acuerdo marco cuelga cada contrato basado/)).toBeInTheDocument();
  });

  it("sin NIF declarado manda a declararlo en vez de decir que no estás", async () => {
    servir({ identidad_conocida: false, admitidos_total: 2, admitidos: ADMITIDOS, organizacion_admitida: null });
    montar("marco");

    const enlace = await screen.findByRole("link", { name: "Declara el NIF de tu organización" });
    expect(enlace).toHaveAttribute("href", "/equipo?tab=organizacion");
    expect(screen.queryByText("No está entre los admitidos")).not.toBeInTheDocument();
  });

  it("con admitidos sin NIF publicado no afirma que no estás", async () => {
    servir({ admitidos_total: 1, admitidos: [{ nombre: "Empresa X", lotes: [] }], organizacion_admitida: null });
    montar("marco");

    expect(await screen.findByText(/no se puede descartar que seas uno de ellos/)).toBeInTheDocument();
  });

  it("un marco sin adjudicar ni duración lo dice", async () => {
    servir({
      sistema: "sda",
      admitidos_total: 0,
      admitidos: [],
      organizacion_admitida: null,
      vigencia: { fecha_fin: null, origen: "desconocida", dias_restantes: null },
    });
    montar("sda");

    expect(await screen.findByText(/no ha publicado admitidos/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sistema dinámico de adquisición" })).toBeInTheDocument();
    expect(screen.getByText("La fuente no publica fecha de fin ni duración.")).toBeInTheDocument();
    expect(screen.queryByText(/^Ver l/)).not.toBeInTheDocument();
  });

  it("en un contrato basado los admitidos que compiten son sin dato y no se pide nada", () => {
    const fetchMock = servir({});
    montar("basado_marco");

    expect(screen.getByRole("heading", { name: "Contrato basado en un acuerdo marco" })).toBeInTheDocument();
    expect(screen.getByText(/Solo pueden presentar oferta las empresas ya admitidas/)).toBeInTheDocument();
    expect(screen.getAllByText("Sin dato", { exact: false }).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/no publica de qué acuerdo marco cuelga este contrato/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
