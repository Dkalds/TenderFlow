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
  sessionStorage.clear();
});

const CON_CAMBIOS = {
  licitacion_id: "EXP-1",
  desde: "2026-10-30T09:00:00+00:00",
  items: [
    {
      subtipo: "documento_nuevo",
      titulo: "Documento nuevo",
      detalle: "Pliego técnico.",
      licitacion_id: "EXP-1",
      cuando: "2026-11-01T08:00:00+00:00",
    },
  ],
  visto_en: "2026-11-02T10:00:00+00:00",
};

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

    expect(await screen.findByRole("region", { name: /Ha cambiado desde tu última visita/ })).toBeInTheDocument();
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

  it("cada cambio lleva a la sección de la ficha donde se ve", async () => {
    apiMutate.mockResolvedValue(CON_CAMBIOS);
    render(<FichaNovedades licitacionId="EXP-1" />);

    expect(await screen.findByRole("link", { name: "Documento nuevo" })).toHaveAttribute("href", "#ficha-pliegos");
  });

  it("recargar no borra lo que cambió: la franja dura lo que la pestaña", async () => {
    apiMutate.mockResolvedValue(CON_CAMBIOS);
    render(<FichaNovedades licitacionId="EXP-1" />);
    await screen.findByText("Documento nuevo");
    cleanup();

    // La segunda visita ya no trae cambios: la marca se movió en la primera.
    apiMutate.mockResolvedValue({ ...CON_CAMBIOS, items: [] });
    render(<FichaNovedades licitacionId="EXP-1" />);

    expect(await screen.findByText("Documento nuevo")).toBeInTheDocument();
    await vi.waitFor(() => expect(apiMutate).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Documento nuevo")).toBeInTheDocument();
  });
});
