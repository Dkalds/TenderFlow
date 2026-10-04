/**
 * La pestaña «Resumen» de `licitacion-ai.tsx` cuando la API rechaza la petición.
 *
 * Va con el `streamResumen` de verdad y el `fetch` doblado: lo que se fija es
 * el camino entero, de la respuesta `application/problem+json` al panel. El
 * 2026-10-04 un 403 en producción era el token CSRF caducado y aquí solo se
 * leía «Error 403».
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("react-markdown", () => ({
  default: ({ children }: { children: string }) => <p>{children}</p>,
}));
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

import { LicitacionAI } from "@/components/licitacion-ai";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LicitacionAI — el resumen falla", () => {
  it("enseña el mensaje humano y deja plegado el motivo que dio la API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            type: "https://licitaciones-sap/errors/forbidden",
            title: "Forbidden",
            status: 403,
            detail: "CSRF token mismatch",
          }),
          { status: 403, headers: { "content-type": "application/problem+json" } },
        ),
      ),
    );

    render(<LicitacionAI idExterno="EXP-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Generar resumen" }));

    const aviso = await screen.findByRole("alert");
    expect(aviso).toHaveTextContent("No se pudo generar el resumen");
    expect(aviso).toHaveTextContent("No tienes permiso para ver esto.");

    const plegado = screen.getByText("Detalle técnico").closest("details");
    expect(plegado).not.toHaveAttribute("open");
    expect(plegado).toHaveTextContent("403 · POST /api/v1/licitaciones/EXP-1/resumen — CSRF token mismatch");
    // El motivo crudo no sale del plegado.
    expect(screen.getByText(/CSRF token mismatch/).closest("details")).toBe(plegado);
  });
});
