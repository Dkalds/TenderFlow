/**
 * El perfil del competidor en franja.
 *
 * Fija lo que la franja promete frente al panel lateral que sustituye: que
 * «Contra ti» está a la vista con el recuento de cada resultado, que una
 * comunidad sin casilla no se pierde, que el resto de órganos es lo que falta
 * hasta 100 y no la suma de lo recibido, y que una empresa sin identidad en el
 * maestro lo dice en vez de quedarse cargando.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { CompanyProfileData } from "@/components/competitors/company-profile-types";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Schemas } from "@/lib/api-types";

const { fetchWithAuth } = vi.hoisted(() => ({ fetchWithAuth: vi.fn() }));
// Solo la red es de mentira: el mensaje de un fallo lo sigue componiendo el
// módulo real (`ApiError`), que es lo que pinta `PanelError`.
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  fetchWithAuth,
}));

vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 1,
  organizacionResuelta: () => true,
}));

// «Vigilar» es el control único `SeguirBoton` (ADR-031 §C). Estos tests miran
// el perfil, no el seguimiento: un estado fijo y sin red basta.
vi.mock("@/hooks/use-seguimiento", () => ({
  useSeguimiento: () => ({
    ids: new Set<string>(),
    sigue: () => false,
    alternar: vi.fn(() => true),
    seguir: vi.fn(),
    dejar: vi.fn(),
    isLoading: false,
    enVuelo: false,
  }),
}));

import { CompetidorPerfil } from "../_components/competidor-perfil";

import { ACME, GAMMA } from "./competidores-fixtures";

const desglose = (label: string, cuota_empresa_pct: number, contratos = 1) => ({
  codigo: null,
  label,
  contratos,
  importe: 0,
  cuota_empresa_pct,
});

const PERFIL: CompanyProfileData = {
  empresa: { empresa_id: 1, nombre: "Acme Sistemas", nif: null, es_ute: false, grupo: null },
  scope: { fecha_desde: null, fecha_hasta: null, cpv: null, ccaas: [], tecnologias: [], importe_min: null },
  actividad_historica: { contratos: 20, importe_total: 2_000_000, primera_adjudicacion: null, ultima_adjudicacion: null },
  totales: {
    contratos: 10,
    importe_total: 1_000_000,
    importe_mediano: 80_000,
    ofertas_medias: 3.5,
    baja_media_pct: 20,
    pct_oferta_unica: 10,
    cobertura_ofertas_pct: 100,
    primera_adjudicacion: null,
    ultima_adjudicacion: null,
    organos: 9,
    territorios: 3,
    familias_cpv: 1,
  },
  posicion_mercado: { rank: 2, empresas: 214, cuota_pct: 38, importe_segmento: 2_500_000 },
  comparacion: {
    desde: "2025-01-01",
    hasta: "2025-12-31",
    anterior_desde: "2024-01-01",
    anterior_hasta: "2024-12-31",
    contratos: 10,
    contratos_anterior: 8,
    variacion_contratos_pct: 25,
    importe: 1_000_000,
    importe_anterior: 800_000,
    variacion_importe_pct: 25,
  },
  concentracion_clientes: { organo_principal: "Ministerio A", top1_contratos_pct: 40, top1_importe_pct: 40, top3_importe_pct: 70 },
  por_cpv: [],
  por_ccaa: [desglose("Madrid", 60, 6), desglose("Cataluña", 25, 3), desglose("Extranjero", 15, 1)],
  organos_principales: [desglose("Ministerio A", 40), desglose("Agencia B", 20), desglose("Ayuntamiento C", 10)],
  por_anio: [
    { anio: 2023, contratos: 4, importe: 400_000 },
    { anio: 2024, contratos: 6, importe: 600_000 },
  ],
  movimientos: [],
  participaciones_ute: [],
};

const batalla = (n: number, resultado: Schemas["Batalla"]["resultado"]): Schemas["Batalla"] => ({
  licitacion_id: `LIC-${n}`,
  titulo: `Expediente ${n}`,
  resultado,
  contradiccion: false,
});

function contraMi(resultados: Schemas["Batalla"]["resultado"][]): Schemas["BatallasContraMi"] {
  return {
    empresa_key: "1",
    n: resultados.length,
    ventana: "últimos 24 meses",
    sin_nif_propio: false,
    contradicciones: 0,
    claves: ["1"],
    batallas: resultados.map((r, i) => batalla(i + 1, r)),
  };
}

function renderPerfil(props: Partial<React.ComponentProps<typeof CompetidorPerfil>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <CompetidorPerfil
          empresa={ACME}
          rango={2}
          ordenTxt="importe"
          totalEmpresas={214}
          empresaId={1}
          empresaIds={[1]}
          perfil={PERFIL}
          isLoading={false}
          enDuelo={false}
          onClose={vi.fn()}
          {...props}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  fetchWithAuth.mockReset();
});

describe("CompetidorPerfil", () => {
  it("dice quién es y qué puesto ocupa por la medida activa", () => {
    fetchWithAuth.mockResolvedValue(contraMi([]));
    renderPerfil();

    expect(screen.getByRole("heading", { level: 2, name: "Acme Sistemas" })).toBeInTheDocument();
    expect(screen.getByText("Perfil del competidor · n.º 2 de 214 por importe")).toBeInTheDocument();
  });

  it("la cuota y el puesto salen los dos del perfil, no uno de cada sitio", () => {
    fetchWithAuth.mockResolvedValue(contraMi([]));
    renderPerfil();

    // La fila del ranking dice 40 %; el perfil, 38 % y n.º 2 en su universo.
    expect(screen.getByText("38,0% · n.º 2")).toBeInTheDocument();
    expect(screen.getByText("Entre 214 empresas")).toBeInTheDocument();
  });

  it("«Contra ti» está a la vista, con el recuento de cada resultado", async () => {
    fetchWithAuth.mockResolvedValue(contraMi(["ellos_ganaron", "ellos_ganaron", "ganamos", "sin_resolver"]));
    renderPerfil();

    expect(await screen.findByText("Ganaron ellos: 2")).toBeInTheDocument();
    expect(screen.getByText("Ganamos: 1")).toBeInTheDocument();
    expect(screen.getByText("Sin resolver: 1")).toBeInTheDocument();
    expect(screen.queryByText(/^Perdimos:/)).not.toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Expedientes en común" })).getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getByText("4 en común en los últimos 24 meses")).toBeInTheDocument();
  });

  it("sin expedientes en común lo dice, sin casillas vacías", async () => {
    fetchWithAuth.mockResolvedValue(contraMi([]));
    renderPerfil();

    expect(await screen.findByText(/no presentó oferta en ningún expediente/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Expedientes en común" })).not.toBeInTheDocument();
  });

  it("cruza «Contra ti» con todas las identidades del grupo", async () => {
    fetchWithAuth.mockResolvedValue(contraMi([]));
    renderPerfil({ empresaId: 7, empresaIds: [7, 8, 9] });

    await screen.findByText(/no presentó oferta/);
    const url = new URL(String(fetchWithAuth.mock.calls[0][0]), "http://localhost");
    expect(url.pathname).toBe("/api/v1/competitive/empresas/7/contra-mi");
    expect(url.searchParams.get("empresa_ids")).toBe("7,8,9");
  });

  it("una comunidad sin casilla no se pierde: se dice fuera del mapa", () => {
    fetchWithAuth.mockResolvedValue(contraMi([]));
    renderPerfil();

    expect(screen.getByText(/Madrid 60% · Cataluña 25%/)).toBeInTheDocument();
    expect(screen.getByText(/fuera del mapa: Extranjero 15%/)).toBeInTheDocument();
    expect(screen.getByText("3 territorios")).toBeInTheDocument();
  });

  it("el resto de órganos es lo que falta hasta 100, no la suma de lo recibido", () => {
    fetchWithAuth.mockResolvedValue(contraMi([]));
    renderPerfil();

    // 40 + 20 + 10 = 70 con nombre; los otros 6 de sus 9 órganos se llevan el 30 %.
    const quien = screen.getByRole("heading", { name: "Quién le compra" }).closest("section")!;
    expect(within(quien).getByText("Otros 6 órganos").closest("li")).toHaveTextContent("30%");
    expect(within(quien).getByText("Ministerio A").closest("li")).toHaveTextContent("40%");
  });

  it("enlaza al análisis completo con las identidades del grupo", () => {
    fetchWithAuth.mockResolvedValue(contraMi([]));
    renderPerfil({ empresaId: 7, empresaIds: [7, 8] });

    expect(screen.getByRole("link", { name: "Ver análisis y listado completo" })).toHaveAttribute(
      "href",
      "/competencia/empresa/7?ids=7,8",
    );
  });

  it("mientras llega el perfil, las cifras son las de la fila del ranking", () => {
    renderPerfil({ perfil: undefined, isLoading: true });

    // 40 % es la cuota de la fila; el perfil aún no ha dicho la suya.
    expect(screen.getByText("40,0%")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Dónde gana" })).not.toBeInTheDocument();
  });

  it("una empresa sin identidad en el maestro lo dice y no pide nada", () => {
    renderPerfil({ empresa: GAMMA, empresaId: undefined, empresaIds: [], perfil: undefined });

    expect(screen.getByRole("heading", { name: "Sin identidad en el maestro de empresas" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Buscarla en Empresas" })).toHaveAttribute(
      "href",
      "/empresas?q=Gamma%20Redes",
    );
    expect(fetchWithAuth).not.toHaveBeenCalled();
    // Gamma no trae baja media: la celda lleva la raya, no un 0 %.
    expect(screen.getByText("Baja media").closest("[data-slot=stat-cell]")).toHaveTextContent("—");
  });

  it("si el perfil falla lo dice, con su reintento", () => {
    const onRetry = vi.fn();
    renderPerfil({ perfil: undefined, error: new Error("boom"), onRetry });

    expect(screen.getByText("No se pudo cargar el perfil")).toBeInTheDocument();
    screen.getByRole("button", { name: "Reintentar" }).click();
    expect(onRetry).toHaveBeenCalled();
  });
});
