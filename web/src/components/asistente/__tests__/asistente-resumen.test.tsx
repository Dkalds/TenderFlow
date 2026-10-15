/**
 * El resumen del expediente cuando la API rechaza la petición, de punta a punta
 * en el asistente único.
 *
 * Era el suite de la pestaña «Resumen» de `licitacion-ai.tsx`. Va con el
 * `useChat` y el `streamResumen` de verdad y el `fetch` doblado: lo que se fija
 * es el camino entero, de la respuesta `application/problem+json` al hilo. El
 * 2026-10-04 un 403 en producción era el token CSRF caducado y aquí solo se
 * leía «Error 403».
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

vi.mock("react-markdown", () => ({
  default: ({ children }: { children: string }) => <p>{children}</p>,
}));
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

import { AsistentePanel } from "@/components/asistente/asistente-panel";
import { useAsistente } from "@/lib/asistente-store";

beforeEach(() => {
  useAsistente.getState().reiniciar();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Asistente — el resumen falla", () => {
  it("enseña el mensaje humano y deja plegado el motivo que dio la API", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          type: "https://licitaciones-sap/errors/forbidden",
          title: "Forbidden",
          status: 403,
          detail: "CSRF token mismatch",
        }),
        { status: 403, headers: { "content-type": "application/problem+json" } },
      ),
    );
    vi.stubGlobal("fetch", fetch);

    render(<AsistentePanel />);
    act(() =>
      useAsistente.getState().abrir({ contexto: { expedientes: [{ id: "EXP-1", titulo: "Soporte" }], origen: "ficha" } }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Resumir el expediente" }));

    const aviso = await screen.findByRole("alert", {}, { timeout: 15_000 });
    expect(aviso).toHaveTextContent("No se pudo obtener la respuesta");
    expect(aviso).toHaveTextContent("No tienes permiso para ver esto.");
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/licitaciones/EXP-1/resumen");

    const plegado = screen.getByText("Detalle técnico").closest("details");
    expect(plegado).not.toHaveAttribute("open");
    expect(plegado).toHaveTextContent("403 · POST /api/v1/licitaciones/EXP-1/resumen — CSRF token mismatch");
    // El motivo crudo no sale del plegado.
    expect(screen.getByText(/CSRF token mismatch/).closest("details")).toBe(plegado);
    // Y no queda un turno vacío del asistente: solo lo que se pidió.
    expect(screen.getByText("Resume el expediente «Soporte»")).toBeInTheDocument();
  });
});
