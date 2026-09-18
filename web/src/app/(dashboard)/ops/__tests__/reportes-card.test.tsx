import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReportesCard } from "../_components/calidad-datos/reportes-card";

/** F6.2 — la vista de Calidad enseña los reportes abiertos por tipo. */
describe("ReportesCard", () => {
  it("etiqueta y ordena los tipos que manda el backend, sin inventar ceros", () => {
    render(<ReportesCard reportes={{ ccaa: 2, duplicado: 5, importe: 0 }} isLoading={false} />);

    const filas = screen.getAllByRole("row").slice(1);
    expect(filas.map((f) => f.textContent)).toEqual([
      "Expediente duplicado5",
      "Comunidad autónoma errónea2",
    ]);
  });

  it("sin reportes lo dice", () => {
    render(<ReportesCard reportes={{}} isLoading={false} />);
    expect(screen.getByText("Ningún reporte abierto.")).toBeInTheDocument();
  });
});
