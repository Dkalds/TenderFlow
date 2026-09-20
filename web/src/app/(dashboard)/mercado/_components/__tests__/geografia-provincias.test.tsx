/**
 * Provincias clicables: cada provincia abre Detalle filtrado por ella (el
 * único listado que aplica `provincia`, F1.1) sin perder el ámbito que ya
 * estaba puesto.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("ccaa=Andaluc%C3%ADa&tecnologia=SAP"),
}));

import { GeografiaTablaProvincias } from "../geografia-tablas";

describe("GeografiaTablaProvincias", () => {
  it("cada provincia enlaza a Detalle con su filtro y el ámbito activo", () => {
    render(
      <GeografiaTablaProvincias
        filas={[{ provincia: "Sevilla", count: 12, importe: 3_000_000 }]}
        sortKey="count"
        sortDir="desc"
        onSort={() => {}}
        isLoading={false}
      />,
    );
    const enlace = screen.getByRole("link", { name: "Ver en Detalle las licitaciones de Sevilla" });
    const href = new URL(enlace.getAttribute("href")!, "http://x");
    expect(href.pathname).toBe("/detalle");
    expect(href.searchParams.get("provincia")).toBe("Sevilla");
    expect(href.searchParams.get("ccaa")).toBe("Andalucía");
    expect(href.searchParams.get("tecnologia")).toBe("SAP");
  });
});
