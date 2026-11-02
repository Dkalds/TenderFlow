import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const { apiMutate } = vi.hoisted(() => ({ apiMutate: vi.fn() }));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiMutate,
}));

import { FichaNovedades } from "@/components/ficha/ficha-novedades";

afterEach(() => {
  cleanup();
  apiMutate.mockReset();
});

describe("FichaNovedades", () => {
  it("registra la visita una sola vez, también con el doble efecto de StrictMode", async () => {
    apiMutate.mockResolvedValue({
      licitacion_id: "EXP-1",
      desde: "2026-10-30T09:00:00+00:00",
      items: [
        {
          subtipo: "plazo_ampliado",
          titulo: "Plazo ampliado",
          detalle: "Del 10 al 20 de noviembre.",
          licitacion_id: "EXP-1",
          cuando: "2026-11-01T08:00:00+00:00",
        },
      ],
      visto_en: "2026-11-02T10:00:00+00:00",
    });
    render(
      <React.StrictMode>
        <FichaNovedades licitacionId="EXP-1" />
      </React.StrictMode>,
    );

    expect(await screen.findByRole("region", { name: "Cambios desde tu última visita" })).toBeInTheDocument();
    expect(screen.getByText("Plazo ampliado")).toBeInTheDocument();
    expect(apiMutate).toHaveBeenCalledTimes(1);
    expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/licitaciones/EXP-1/visita");
  });

  it("la primera visita no pinta franja: no hay con qué comparar", async () => {
    apiMutate.mockResolvedValue({
      licitacion_id: "EXP-1",
      desde: null,
      items: [],
      visto_en: "2026-11-02T10:00:00+00:00",
    });
    render(<FichaNovedades licitacionId="EXP-1" />);

    await vi.waitFor(() => expect(apiMutate).toHaveBeenCalled());
    expect(screen.queryByRole("region")).toBeNull();
  });
});
