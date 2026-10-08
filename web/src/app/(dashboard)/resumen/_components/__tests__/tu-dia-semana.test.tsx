import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { SemanaEnCarriles } from "../tu-dia-semana";
import { semanaEnCarriles } from "../tu-dia-semana-data";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";

function item(id: string, urgencia: PipelineAgendaItem["urgencia"], dias: number): PipelineAgendaItem {
  return {
    kind: "pursuit",
    due_kind: "plazo",
    urgencia,
    dias_restantes: dias,
    licitacion_id: id,
    pursuit_id: null,
    titulo: `Expediente ${id}`,
    organo: "Ayuntamiento",
    importe_eur: 120_000,
  } as PipelineAgendaItem;
}

afterEach(cleanup);

describe("SemanaEnCarriles", () => {
  it("enseña tres compromisos por día y manda el resto a la agenda", () => {
    const hoy = new Date(2026, 9, 8, 12, 0);
    const tramos = semanaEnCarriles(["A", "B", "C", "D"].map((id) => item(id, "hoy", 0)), hoy);
    render(<SemanaEnCarriles tramos={tramos} />);

    const carril = screen.getByRole("heading", { name: "Hoy" }).closest("li");
    expect(carril).not.toBeNull();
    expect(within(carril as HTMLElement).getAllByRole("link", { name: /Expediente/ })).toHaveLength(3);
    expect(within(carril as HTMLElement).getByRole("link", { name: "1 más en la agenda" })).toHaveAttribute(
      "href",
      "/mi-pipeline?vista=agenda",
    );
    // Cada compromiso abre su ficha y dice qué clase de fecha es la del chip.
    expect(screen.getByRole("link", { name: /Expediente A/ })).toHaveAttribute("href", "/detalle?lic=A");
    expect(screen.getAllByText("Plazo")).toHaveLength(3);
    expect(screen.getAllByText(/Plazo de presentación:/)).toHaveLength(3);
  });

  it("junta los días sin nada en un hueco que lo dice", () => {
    const hoy = new Date(2026, 9, 8, 12, 0);
    render(<SemanaEnCarriles tramos={semanaEnCarriles([item("A", "hoy", 0)], hoy)} />);

    expect(screen.getByText("vie 9 – jue 15")).toBeInTheDocument();
    expect(screen.getByText("sin compromisos")).toBeInTheDocument();
  });
});
