import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * S3.1 — la oportunidad abierta por lote pide el escenario **de su lote**.
 *
 * Lo que se vigila aquí es la URL: el panel pintaba tres precios calculados
 * sobre el presupuesto del expediente entero aunque la oportunidad fuera de un
 * único lote, que es el objeto de contrato que nadie iba a firmar.
 */

const fetchWithAuth = vi.hoisted(() => vi.fn((_url: string) => Promise.resolve<unknown>({})));
vi.mock("@/lib/api-client", () => ({ fetchWithAuth }));

// El pursuit de la ruta: de él sale el lote cuando el llamador no lo pasa.
const pursuit = vi.hoisted(() => ({
  data: null as { lote_id: number | null; lote_numero: string | null } | null,
  isLoading: false,
}));
vi.mock("@/hooks/use-pursuits", () => ({ usePursuit: () => pursuit }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "42" }) }));

import { PriceScenariosPanel } from "@/components/pursuits/price-scenarios";

const escenarios = {
  licitacion_id: "LIC-1",
  tender_amount_eur: 40000,
  expected_competition: null,
  cohort: ["cpv4", "importe"],
  sample_quality: "indicativa",
  distribution: {
    n: 12,
    p10_discount: 0.1,
    p25_discount: 0.15,
    p50_discount: 0.2,
    p75_discount: 0.25,
    p90_discount: 0.3,
    observed_interval: [0.1, 0.3],
  },
  scenarios: [
    {
      name: "central",
      discount: 0.2,
      price_eur: 32000,
      basis: "mediana de la baja observada",
      margen_implicito: null,
    },
  ],
  win_probability_gate: { available: false, blockers: [] },
  methodology: "Distribución empírica.",
  disclaimer: "Estos escenarios NO son una P(ganar) causal.",
};

function renderPanel(props: { licitacionId: string; loteId?: number | null }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <PriceScenariosPanel {...props} />
    </QueryClientProvider>,
  );
}

const url = () => fetchWithAuth.mock.calls[0]?.[0];

beforeEach(() => {
  fetchWithAuth.mockReset();
  fetchWithAuth.mockResolvedValue(escenarios);
  pursuit.data = { lote_id: null, lote_numero: null };
  pursuit.isLoading = false;
});

describe("PriceScenariosPanel", () => {
  it("pide el escenario del lote cuando la oportunidad se abrió por lote", async () => {
    pursuit.data = { lote_id: 7, lote_numero: "2" };
    renderPanel({ licitacionId: "LIC-1" });

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalled());
    expect(url()).toBe("/api/v1/licitaciones/LIC-1/escenarios-precio?lote_id=7");
    expect(await screen.findByText("Lote 2")).toBeInTheDocument();
    expect(screen.getByText(/presupuesto del lote 2/)).toBeInTheDocument();
  });

  it("sin lote pide el del expediente, exactamente como antes", async () => {
    renderPanel({ licitacionId: "LIC-1" });

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalled());
    expect(url()).toBe("/api/v1/licitaciones/LIC-1/escenarios-precio");
    expect(await screen.findByText(/adjudicaciones comparables/)).toBeInTheDocument();
    expect(screen.queryByText(/^Lote /)).toBeNull();
  });

  it("un loteId explícito manda sobre el pursuit de la ruta", async () => {
    pursuit.data = { lote_id: 7, lote_numero: "2" };
    renderPanel({ licitacionId: "LIC-1", loteId: null });

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalled());
    expect(url()).toBe("/api/v1/licitaciones/LIC-1/escenarios-precio");
  });

  it("avisa cuando el lote de la oportunidad ya no está publicado", async () => {
    // `lote_id` NULL con `lote_numero` vivo es exactamente lo que devuelve el
    // backend cuando el pliego deja de publicar ese lote (v110): el escenario
    // pasa a ser el del expediente y hay que decirlo.
    pursuit.data = { lote_id: null, lote_numero: "3" };
    renderPanel({ licitacionId: "LIC-1" });

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalled());
    expect(url()).toBe("/api/v1/licitaciones/LIC-1/escenarios-precio");
    expect(await screen.findByText(/ya no figura publicado/)).toBeInTheDocument();
  });
});
