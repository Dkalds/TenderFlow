/**
 * F3.3 — socios de UTE sugeridos en la ficha de la oportunidad.
 *
 * Fija: el segmento se deriva del CPV del expediente sin ceros de cola; cada
 * socio se pinta con su motivo; los líderes van aparte y rotulados como
 * competencia, no como socios; y sin base suficiente la lista vacía se declara
 * con el motivo del backend.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { apiGet, registrarEvento } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  registrarEvento: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({ apiGet }));
vi.mock("@/lib/analytics", () => ({ registrarEvento }));

import { prefijoCpv, SociosUte } from "../socios-ute";

function renderSocios(cpv: string | null, ccaa: string | null = "Madrid") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <SociosUte cpv={cpv} ccaa={ccaa} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  apiGet.mockReset();
  registrarEvento.mockReset();
});

describe("prefijoCpv", () => {
  it.each([
    ["72212000-4", "72212"],
    ["72000000", "72"],
    ["48000000-8, 72000000-5", "48"],
    ["30200000", "302"],
    ["", null],
    [null, null],
    ["X", null],
  ])("%s → %s", (cpv, esperado) => {
    expect(prefijoCpv(cpv)).toBe(esperado);
  });
});

describe("SociosUte", () => {
  it("pide el segmento del expediente y pinta cada socio con su motivo", async () => {
    apiGet.mockResolvedValue({
      socios: [
        {
          empresa: "Consultora Norte",
          empresa_key: "42",
          n_contratos: 7,
          importe_total: 900000,
          n_organos: 4,
          pct_ute: 60,
          es_pyme: true,
          motivos: ["Adjudicataria en 4 órganos distintos de este segmento.", "Es PYME: puede sumar."],
        },
      ],
      lideres: [
        { empresa: "Gran Integrador", empresa_key: "GRAN INTEGRADOR", n_contratos: 30, importe_total: 5_000_000, cuota_pct: 41.5 },
      ],
      n_adjudicaciones: 120,
      cpv: "72212",
      ccaa: "Madrid",
      sin_resultados: null,
    });
    renderSocios("72212000-4");

    expect(await screen.findByText("Consultora Norte")).toHaveAttribute("href", "/competencia/empresa/42");
    expect(apiGet).toHaveBeenCalledWith("/api/v1/competitive/partners", {
      params: { query: { cpv: "72212", ccaa: "Madrid", limit: 5 } },
    });
    expect(screen.getByText("Adjudicataria en 4 órganos distintos de este segmento.")).toBeInTheDocument();
    expect(screen.getByText(/sobre 120 adjudicaciones/)).toBeInTheDocument();
    // Los líderes no se ofrecen como socios, y sin id del maestro no hay enlace.
    expect(screen.getByText(/son contra quién se compite/)).toBeInTheDocument();
    expect(screen.getByText("Gran Integrador").tagName).toBe("SPAN");
    await waitFor(() =>
      expect(registrarEvento).toHaveBeenCalledWith("partners_consultado", { con_resultados: "si" }),
    );
  });

  it("sin base suficiente declara la lista vacía con el motivo del backend", async () => {
    apiGet.mockResolvedValue({
      socios: [],
      lideres: [],
      n_adjudicaciones: 2,
      cpv: "72",
      ccaa: null,
      sin_resultados: "Menos de 3 contratos por empresa en este segmento.",
    });
    renderSocios("72000000", null);

    expect(await screen.findByText("Menos de 3 contratos por empresa en este segmento.")).toBeInTheDocument();
    await waitFor(() =>
      expect(registrarEvento).toHaveBeenCalledWith("partners_consultado", { con_resultados: "no" }),
    );
  });

  it("sin CPV no pide nada y lo dice", () => {
    renderSocios(null);
    expect(screen.getByText(/no trae CPV/)).toBeInTheDocument();
    expect(apiGet).not.toHaveBeenCalled();
  });
});
