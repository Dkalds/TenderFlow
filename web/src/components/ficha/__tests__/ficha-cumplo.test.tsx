import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import type { LicitacionDetail } from "@/lib/licitacion-detail";

vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  organizacionResuelta: () => true,
}));
vi.mock("@/components/competitors/socios-ute", () => ({
  SociosUte: ({ cpv }: { cpv: string | null }) => <p>Socios del CPV {cpv}</p>,
}));

import { FichaCumplo } from "@/components/ficha/ficha-cumplo";

const LICITACION = { id_externo: "PA-S 2026/1", cpv: "72267000", ccaa: "Andalucía" } as LicitacionDetail;

function checklist(cumple: number, noCumple: number) {
  const veredicto = noCumple > 0 ? "no_cumple" : "cumple";
  return {
    licitacion_id: "PA-S 2026/1",
    organization_id: 7,
    ficha_estado: "completed",
    extraction_version: "tender-facts-v8",
    ficha_actualizada: "2026-10-30",
    familias: [
      {
        familia: "certifications",
        etiqueta: "Certificaciones",
        veredicto,
        sin_hechos: false,
        fuente: "pliego",
        items: [
          {
            familia: "certifications",
            requisito: "ISO 27001",
            veredicto,
            motivo: "La organización no la declara.",
            evidencia: [],
            dato_organizacion: null,
            fuente: "pliego",
          },
        ],
      },
    ],
    total_requisitos: cumple + noCumple,
    cumple,
    no_cumple: noCumple,
    desconocido: 0,
    requisitos_extraidos: cumple + noCumple,
    desconocido_extraidos: 0,
    usa_condiciones_oficiales: false,
    condiciones_actualizadas: null,
  };
}

/** El checklist a su URL; los documentos del pliego, vacíos. */
function servir(respuesta: unknown) {
  const fetchMock = vi.fn((...call: unknown[]) =>
    Promise.resolve(jsonResponse(callUrl(call).includes("/checklist") ? respuesta : { items: [] })),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function montar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FichaCumplo licitacion={LICITACION} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("FichaCumplo", () => {
  it("pide el checklist del expediente para la organización activa y da los conteos", async () => {
    const fetchMock = servir(checklist(1, 0));
    montar();

    expect(await screen.findByRole("status")).toHaveTextContent("De 1 requisito: 1 «cumple» · 0 «no cumple»");
    const urls = fetchMock.mock.calls.map((call) => callUrl(call));
    expect(urls).toContain("/api/v1/licitaciones/PA-S%202026%2F1/checklist?organization_id=7");
    expect(screen.queryByText(/Socios del CPV/)).toBeNull();
  });

  it("si algo no se cumple, propone socios para ir en UTE en el segmento", async () => {
    servir(checklist(0, 1));
    montar();

    expect(await screen.findByText("Socios del CPV 72267000")).toBeInTheDocument();
    expect(screen.getByText(/No cumples un requisito/)).toBeInTheDocument();
  });

  it("sin requisitos con los que comparar lo dice en vez de enseñar ceros", async () => {
    servir({ ...checklist(0, 0), ficha_estado: null, familias: [] });
    montar();

    expect(await screen.findByText("Todavía no hay requisitos con los que comparar")).toBeInTheDocument();
  });
});
