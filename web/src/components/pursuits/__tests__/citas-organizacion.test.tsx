/**
 * CU-36 — las citas de documentos propios que acompañan a una respuesta del
 * Investigador o a un criterio del guion: rotuladas, con su origen y con la
 * descarga firmada de siempre. El evento del stream se prueba aquí también,
 * porque es lo que las trae.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CitasOrganizacion } from "@/components/pursuits/citas-organizacion";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import { streamAsk } from "@/lib/ask-stream";
import type { CitaOrganizacion } from "@/lib/api-types";

const guardarFichero = vi.hoisted(() => vi.fn());
vi.mock("@/lib/export", () => ({ guardarFichero }));

vi.mock("@/hooks/use-organization", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-organization")>();
  return { ...actual, useActiveOrganizationId: () => 7 };
});

const CITA: CitaOrganizacion = {
  attachment_id: 11,
  filename: "Propuesta técnica.pdf",
  page_number: 3,
  cita: "Migramos el ERP de la Diputación en nueve meses.",
  pursuit_id: 42,
  licitacion_id: "EXP-1",
  licitacion_titulo: "Migración del ERP provincial",
};

function montar(citas: CitaOrganizacion[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CitasOrganizacion citas={citas} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  guardarFichero.mockClear();
});

describe("CitasOrganizacion", () => {
  it("rotula el extracto como documento de la organización, con fichero, página y oportunidad", () => {
    montar([CITA, { ...CITA, attachment_id: 12, filename: "Anexo.txt", page_number: null, licitacion_titulo: null }]);

    expect(screen.getByText("De documentos de tu organización (2)")).toBeInTheDocument();
    expect(screen.getByText("Propuesta técnica.pdf, p. 3")).toBeInTheDocument();
    expect(screen.getAllByText("Migramos el ERP de la Diputación en nueve meses.")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Oportunidad: Migración del ERP provincial" })).toHaveAttribute(
      "href",
      "/oportunidades/42",
    );
    // Sin página ni título, se dice lo que hay: el fichero y el expediente.
    expect(screen.getByText("Anexo.txt")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Oportunidad: EXP-1" })).toBeInTheDocument();
  });

  it("sin citas no ocupa sitio", () => {
    const { container } = montar([]);
    expect(container).toBeEmptyDOMElement();
  });

  it("descarga el fichero por el enlace firmado, con la organización", async () => {
    const fetchMock = vi.fn((...call: unknown[]) => {
      const url = callUrl(call);
      if (url.startsWith("/api/v1/pursuits/adjuntos/11/enlace")) {
        return Promise.resolve(jsonResponse({ path: "/api/v1/pursuits/adjuntos/11/descargar?exp=9&t=abc", expira_en: 9 }));
      }
      return Promise.resolve(new Response("%PDF", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    montar([CITA]);

    fireEvent.click(screen.getByRole("button", { name: "Descargar Propuesta técnica.pdf" }));

    await waitFor(() => expect(guardarFichero).toHaveBeenCalledWith("Propuesta técnica.pdf", expect.anything()));
    expect(fetchMock.mock.calls.map((call) => callUrl(call))).toEqual([
      "/api/v1/pursuits/adjuntos/11/enlace?organization_id=7",
      "/api/v1/pursuits/adjuntos/11/descargar?exp=9&t=abc&organization_id=7",
    ]);
  });
});

describe("evento fuentes_organizacion del asistente", () => {
  it("llega al resultado y al callback sin mezclarse con las fuentes del pliego", async () => {
    const encoder = new TextEncoder();
    const cuerpo = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ fuentes_organizacion: [CITA] })}\n`));
        controller.enqueue(encoder.encode('data: {"text": "respuesta"}\n'));
        controller.enqueue(encoder.encode("data: [DONE]\n"));
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(cuerpo, { headers: { "content-type": "text/event-stream" } })),
    );
    const recibidas: CitaOrganizacion[][] = [];

    const resultado = await streamAsk({
      question: "¿qué metodología seguimos?",
      onToken: () => {},
      onFuentesOrganizacion: (citas) => recibidas.push(citas),
    });

    expect(recibidas).toEqual([[CITA]]);
    expect(resultado.fuentesOrganizacion).toEqual([CITA]);
    expect(resultado.fuentes).toEqual([]);
    expect(resultado.answer).toBe("respuesta");
  });
});
