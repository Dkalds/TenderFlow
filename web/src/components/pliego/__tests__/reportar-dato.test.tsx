/**
 * F6.2 — reportar un dato incorrecto.
 *
 * Se fija: el cuerpo va con el tipo cerrado y el comentario; el acuse dice a
 * qué revisión llegó (la `cola` de la API) en vez de un «gracias» vacío; y la
 * telemetría sale después del 201 y sólo con el tipo.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";

vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

import { registrarEvento } from "@/lib/analytics";
import { callMethod, callUrl } from "@/hooks/__tests__/fetch-call";
import { ReportarDatoBoton } from "@/components/pliego/reportar-dato";
import { TIPOS_REPORTE } from "@/hooks/use-reportar-dato";
import { fetchPorRuta, renderConQuery } from "./pliego-render";

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("ReportarDatoBoton", () => {
  it("ofrece todos los tipos de la API y no envía sin elegir uno", () => {
    fetchPorRuta();
    renderConQuery(<ReportarDatoBoton licitacionId="LIC-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Reportar dato" }));

    const dialogo = screen.getByRole("dialog");
    expect(dialogo).toHaveTextContent("Reportar un dato incorrecto");
    expect(screen.getAllByRole("radio")).toHaveLength(Object.keys(TIPOS_REPORTE).length);
    expect(screen.getByRole("button", { name: "Enviar reporte" })).toBeDisabled();
  });

  it("envía tipo y comentario, dice a qué revisión llega y cuenta el tipo", async () => {
    const fetch = fetchPorRuta([
      /reportes$/,
      { id_externo: "LIC-1", tipo: "duplicado", cola: "dedupe", created_at: "2026-09-18T10:00:00Z" },
      201,
    ]);
    renderConQuery(<ReportarDatoBoton licitacionId="LIC-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Reportar dato" }));

    fireEvent.click(screen.getByRole("radio", { name: "Expediente duplicado" }));
    fireEvent.change(screen.getByLabelText(/Comentario/), { target: { value: " Es el mismo que LIC-0 " } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar reporte" }));

    expect(await screen.findByText(/la revisión de duplicados/)).toBeInTheDocument();
    const llamada = fetch.mock.calls[0];
    expect(callUrl(llamada)).toBe("/api/v1/licitaciones/LIC-1/reportes");
    expect(callMethod(llamada)).toBe("POST");
    expect(JSON.parse(String((llamada[1] as RequestInit).body))).toEqual({
      tipo: "duplicado",
      comentario: "Es el mismo que LIC-0",
    });
    expect(registrarEvento).toHaveBeenCalledWith("dato_reportado", { tipo: "duplicado" });
  });

  it("un fallo se dice y no cuenta como reporte", async () => {
    fetchPorRuta([/reportes$/, { detail: "Servicio no disponible" }, 503]);
    renderConQuery(<ReportarDatoBoton licitacionId="LIC-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Reportar dato" }));
    fireEvent.click(screen.getByRole("radio", { name: "Otro" }));
    fireEvent.click(screen.getByRole("button", { name: "Enviar reporte" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo enviar el reporte");
    expect(registrarEvento).not.toHaveBeenCalled();
  });
});
