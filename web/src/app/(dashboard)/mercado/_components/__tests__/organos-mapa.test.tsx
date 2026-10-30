/**
 * Mapa de compradores: los ejes son logarítmicos, así que un órgano sin importe
 * no se puede dibujar. Se queda fuera del gráfico y la leyenda dice cuántos.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { PuntoOrgano } from "../../_hooks/use-organos-view";
import { OrganosMapa } from "../organos-mapa";

const dibujados: string[][] = [];
vi.mock("next/dynamic", () => ({
  default: () =>
    function GraficoFalso({ puntos }: { puntos: PuntoOrgano[] }) {
      dibujados.push(puntos.map((p) => p.organo));
      return null;
    },
}));

function punto(organo: string, count: number, importe: number): PuntoOrgano {
  return { organo, count, importe, medio: count > 0 ? importe / count : 0, etiqueta: "", seleccionado: false };
}

describe("OrganosMapa", () => {
  it("no dibuja los órganos sin importe y dice cuántos quedan fuera", () => {
    render(
      <OrganosMapa
        puntos={[punto("Correos", 96, 72_100_000), punto("Consorci Sanitari", 2, 0), punto("Ayuntamiento", 4, 0)]}
        medianas={{ count: 4, importe: 0 }}
        filtrado={false}
        isLoading={false}
        onOrganoClick={() => {}}
      />,
    );
    expect(dibujados.at(-1)).toEqual(["Correos"]);
    expect(screen.getByText("2 órganos sin importe conocido no aparecen en el mapa")).toBeInTheDocument();
  });

  it("sin órganos fuera, no hay aviso", () => {
    render(
      <OrganosMapa
        puntos={[punto("Correos", 96, 72_100_000), punto("SAS", 148, 61_400_000)]}
        medianas={{ count: 122, importe: 66_750_000 }}
        filtrado={false}
        isLoading={false}
        onOrganoClick={() => {}}
      />,
    );
    expect(screen.queryByText(/no aparece/)).not.toBeInTheDocument();
  });
});
