import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import {
  OrganosAdjudicatariosChart,
  OrganosEstacionalidadChart,
  OrganosMapaChart,
  type PuntoMapaOrgano,
} from "@/components/charts/organos-charts";

const PUNTOS: PuntoMapaOrgano[] = [
  { organo: "Servicio Andaluz de Salud", count: 148, importe: 61_400_000, medio: 414_865, etiqueta: "Servicio Andaluz de Salud", seleccionado: true },
  { organo: "Correos", count: 96, importe: 72_100_000, medio: 751_042, etiqueta: "Correos", seleccionado: false },
  { organo: "Consorci Sanitari", count: 2, importe: 0, medio: 0, etiqueta: "", seleccionado: false },
];

describe("organos charts", () => {
  it("renders the buyers map with its medians and quadrants", () => {
    const onOrganoClick = vi.fn();
    expect(() =>
      render(
        <OrganosMapaChart
          puntos={PUNTOS}
          medianaCount={96}
          medianaImporte={61_400_000}
          onOrganoClick={onOrganoClick}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the buyers map without medians (fewer than two organs)", () => {
    expect(() =>
      render(
        <OrganosMapaChart
          puntos={PUNTOS.slice(0, 1)}
          medianaCount={null}
          medianaImporte={null}
          onOrganoClick={() => {}}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the adjudicatarios chart", () => {
    expect(() =>
      render(
        <OrganosAdjudicatariosChart
          data={[
            { nombre: "Indra Soluciones TI", count: 12, importe: 18_200_000 },
            { nombre: "Accenture", count: 7, importe: 11_900_000 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the seasonality chart at a custom height", () => {
    expect(() =>
      render(
        <OrganosEstacionalidadChart
          data={[
            { mes_numero: 1, count: 6 },
            { mes_numero: 11, count: 12 },
          ]}
          height={150}
        />,
      ),
    ).not.toThrow();
  });
});
