/**
 * Las acciones de la cabecera de una oportunidad: el PDF para dirección,
 * preguntar a la IA, el expediente en Detalle y cerrar.
 *
 * «Preguntar a la IA» es nueva en 2026-10: abre el asistente único con el
 * expediente de la oportunidad, igual que desde su ficha en Detalle, sin salir
 * de la pantalla donde se decide.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const { triggerDownload } = vi.hoisted(() => ({ triggerDownload: vi.fn() }));
vi.mock("@/lib/export", () => ({ triggerDownload }));

import { AccionesCabecera } from "../_components/acciones-cabecera";
import { useAsistente } from "@/lib/asistente-store";

const PURSUIT = { id: 42, licitacion_id: "ES-2026-77", tender_title: "Soporte SAP S/4HANA" };

beforeEach(() => useAsistente.getState().reiniciar());
afterEach(cleanup);

describe("AccionesCabecera", () => {
  it("«Preguntar a la IA» abre el asistente con el expediente de la oportunidad", () => {
    render(<AccionesCabecera pursuit={PURSUIT} />);

    fireEvent.click(screen.getByRole("button", { name: "Preguntar a la IA" }));

    const estado = useAsistente.getState();
    expect(estado.abierto).toBe(true);
    expect(estado.contexto).toEqual({
      expedientes: [{ id: "ES-2026-77", titulo: "Soporte SAP S/4HANA" }],
      origen: "oportunidad",
    });
  });

  it("sin título, el expediente se nombra por su referencia", () => {
    render(<AccionesCabecera pursuit={{ ...PURSUIT, tender_title: null }} />);
    fireEvent.click(screen.getByRole("button", { name: "Preguntar a la IA" }));
    expect(useAsistente.getState().contexto.expedientes).toEqual([
      { id: "ES-2026-77", titulo: "Licitación ES-2026-77" },
    ]);
  });

  it("conserva el PDF, el expediente en Detalle y el cierre", () => {
    render(<AccionesCabecera pursuit={PURSUIT} />);

    fireEvent.click(screen.getByRole("button", { name: "Descargar PDF" }));
    expect(triggerDownload).toHaveBeenCalledWith("/api/v1/pursuits/42/ficha.pdf");
    expect(screen.getByRole("link", { name: "Ver en Detalle" })).toHaveAttribute("href", "/detalle?lic=ES-2026-77");
    expect(screen.getByRole("link", { name: "Cerrar la ficha" })).toHaveAttribute("href", "/oportunidades");
  });
});
