/**
 * F1.7 + F1.8 — el código CODICE legible y su ayuda.
 *
 * Lo que se fija: la etiqueta sale de `/meta/filters` (no de una copia local),
 * un código desconocido se ve tal cual con su aviso, y abrir la ayuda mide
 * `glosario_abierto` **una vez** y sin el término.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";

const { registrarEvento } = vi.hoisted(() => ({ registrarEvento: vi.fn() }));
vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  registrarEvento,
}));

import { CodigoLegible } from "@/components/codigo-legible";

const META = {
  estado: [],
  ccaa: [],
  tecnologia: [],
  cpv: [],
  procedimiento: [
    { codigo: "1", etiqueta: "Abierto", descripcion: "Cualquier empresa puede presentar oferta." },
  ],
  tramitacion: [],
  tipo_contrato: [],
};

function pintar(codigo: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <CodigoLegible familia="procedimiento" codigo={codigo} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  window.history.replaceState(null, "", "/radar");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, status: 200, json: async () => META })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  registrarEvento.mockReset();
});

describe("CodigoLegible", () => {
  it("pinta la etiqueta del catálogo con su ayuda", async () => {
    pintar("01");
    expect(await screen.findByText("Abierto")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Qué es Abierto" })).toBeInTheDocument();
  });

  it("un código desconocido se ve tal cual con el aviso de no catalogado", async () => {
    pintar("77");
    expect(await screen.findByText("(código no catalogado)")).toBeInTheDocument();
    expect(screen.getByText("77")).toBeInTheDocument();
  });

  it("abrir la ayuda mide glosario_abierto una sola vez y sin el término", async () => {
    pintar("1");
    const ayuda = await screen.findByRole("button", { name: "Qué es Abierto" });
    act(() => {
      fireEvent.focus(ayuda);
    });
    await waitFor(() => expect(registrarEvento).toHaveBeenCalledTimes(1));
    expect(registrarEvento).toHaveBeenCalledWith("espacio_abierto", {
      espacio: "radar",
      origen: "glosario",
      glosario_abierto: "si",
    });
    act(() => {
      fireEvent.blur(ayuda);
      fireEvent.focus(ayuda);
    });
    expect(registrarEvento).toHaveBeenCalledTimes(1);
  });
});
