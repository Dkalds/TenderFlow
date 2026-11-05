import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { respuestaDeContrato } from "@/test/contrato";
import { TecnologiasTopScore } from "../tecnologias-tablas";

/**
 * «Las 20 licitaciones mejor puntuadas» leía `item.id`, que la API no manda
 * (`ScoredOpportunity` trae `id_externo`): pintaba el id vacío y no enlazaba a
 * la ficha. Y coloreaba con `score >= 80` cuando la banda la decide el backend.
 */

afterEach(cleanup);

const [OPORTUNIDAD] = respuestaDeContrato("/api/v1/analytics/scoring").opportunities ?? [];

function montar(items = [OPORTUNIDAD]) {
  render(
    <TooltipProvider>
      <TecnologiasTopScore items={items} />
    </TooltipProvider>,
  );
}

describe("TecnologiasTopScore", () => {
  it("enseña el expediente y enlaza el título a su ficha", () => {
    montar();
    expect(screen.getByText(OPORTUNIDAD.id_externo)).toBeInTheDocument();
    const enlace = screen.getByRole("link", { name: OPORTUNIDAD.titulo ?? "" });
    expect(enlace).toHaveAttribute("href", `/detalle?lic=${encodeURIComponent(OPORTUNIDAD.id_externo)}`);
  });

  it("pinta la banda del backend, no un umbral local del score", () => {
    // 79 con banda Caliente: con el umbral de 80 habría salido como secundaria.
    montar([{ ...OPORTUNIDAD, score: 79, band: "Caliente" }]);
    expect(screen.getByText("Caliente")).toHaveAttribute("data-slot", "chip-banda");
    expect(screen.getByText("79")).toBeInTheDocument();
  });

  it("sin título, el enlace lleva el expediente", () => {
    montar([{ ...OPORTUNIDAD, titulo: null }]);
    expect(screen.getByRole("link", { name: OPORTUNIDAD.id_externo })).toBeInTheDocument();
  });
});
