/**
 * F2.8 — preguntar sobre los expedientes de la bandeja de comparación.
 *
 * Se fija: la pregunta viaja con los tres ids (`ids_externos`), la respuesta
 * se pinta con sus citas por expediente, y una comparación incompleta —un
 * expediente que no cargó o que llegó recortado— se dice con nombre.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  registrarEvento: vi.fn(),
}));

import { PreguntaComparacion } from "@/components/pliego/pregunta-comparacion";

function sse(lineas: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const l of lineas) controller.enqueue(encoder.encode(l));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

afterEach(() => vi.unstubAllGlobals());

const META = {
  ask_meta: {
    contexto: "comparacion",
    id_externo: null,
    ids_externos: ["A", "B", "C"],
    truncado: true,
    expedientes: [
      { id_externo: "A", encontrado: true, has_pliego_text: true, fragmentos: 3, truncado: false },
      { id_externo: "B", encontrado: false },
      { id_externo: "C", encontrado: true, has_pliego_text: true, fragmentos: 3, truncado: true },
    ],
  },
};

describe("PreguntaComparacion", () => {
  it("pregunta sobre los tres y avisa de lo que no entró", async () => {
    const fetch = vi.fn().mockResolvedValue(
      sse([
        `data: ${JSON.stringify(META)}\n\n`,
        'data: {"text": "[A] pide 3 años [doc:10 p.2]."}\n\n',
        `data: ${JSON.stringify({
          sources: [
            { documento_id: 10, page_number: 2, cita: "tres años", filename: "PCAP.pdf", id_externo: "A" },
          ],
          sin_fuentes: false,
          descartadas: 0,
        })}\n\n`,
        "data: [DONE]\n\n",
      ]),
    );
    vi.stubGlobal("fetch", fetch);

    render(
      <PreguntaComparacion ids={["A", "B", "C"]} etiquetas={{ A: "Uno", B: "Dos", C: "Tres" }} />,
    );
    expect(screen.getByText(/Preguntar sobre estos 3 expedientes/)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: /expedientes comparados/ }), {
      target: { value: "¿Qué solvencia piden?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar pregunta" }));

    expect(await screen.findByText("Comparación incompleta")).toBeInTheDocument();
    expect(screen.getByText("No se pudo cargar: B.")).toBeInTheDocument();
    expect(screen.getByText(/Pliego recortado para que quepan todos: C\./)).toBeInTheDocument();
    expect(await screen.findByText(/A · PCAP\.pdf, p\. 2/)).toBeInTheDocument();
    // Una comparación no es «respuesta sin el contexto del expediente».
    expect(screen.queryByText("Respuesta sin el contexto de este expediente")).toBeNull();

    const cuerpo = JSON.parse(fetch.mock.calls[0][1].body);
    expect(cuerpo.ids_externos).toEqual(["A", "B", "C"]);
  });
});
