import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import {
  CompetidoresMapaChart,
  ladosDe,
  type PuntoMapaCompetidor,
} from "@/components/charts/competitors-charts";

const empresa = (nombre: string): PuntoMapaCompetidor["empresa"] => ({
  nombre,
  count: 12,
  importe: 900_000,
  cuota: 8,
  contratos_por_anio: 3,
  importe_medio: 75_000,
  n_organos: 4,
  pct_top_organo: 40,
  es_agrupacion: false,
});

const punto = (nombre: string, over: Partial<PuntoMapaCompetidor> = {}): PuntoMapaCompetidor => ({
  nombre,
  x: 12,
  y: 75_000,
  cuota: 8,
  etiqueta: nombre,
  seleccionado: false,
  vigilada: false,
  empresa: empresa(nombre),
  ...over,
});

describe("ladosDe", () => {
  // En `ReferenceArea` el lado que falta se va al borde del lienzo. Con `y1`
  // en los de arriba, el tinte y los rótulos «Contratos grandes…» se pintaban
  // por debajo de la mediana: el cuadrante al revés.
  it("un cuadrante de arriba va de su suelo (y2) al borde superior", () => {
    expect(ladosDe("arribaDerecha", 10, 500)).toEqual({ x1: 10, y2: 500 });
    expect(ladosDe("arribaIzquierda", 10, 500)).toEqual({ x2: 10, y2: 500 });
  });

  it("un cuadrante de abajo va de su techo (y1) al borde inferior", () => {
    expect(ladosDe("abajoDerecha", 10, 500)).toEqual({ x1: 10, y1: 500 });
    expect(ladosDe("abajoIzquierda", 10, 500)).toEqual({ x2: 10, y1: 500 });
  });
});

describe("CompetidoresMapaChart", () => {
  const puntos = [punto("A", { seleccionado: true }), punto("B", { x: 4, y: 20_000, vigilada: true })];

  it("pinta la lente de precio, con su eje logarítmico", () => {
    expect(() =>
      render(
        <CompetidoresMapaChart puntos={puntos} lente="precio" medianaX={8} medianaY={47_500} onEmpresaClick={vi.fn()} />,
      ),
    ).not.toThrow();
  });

  it("pinta la lente de clientes", () => {
    expect(() =>
      render(
        <CompetidoresMapaChart puntos={puntos} lente="clientes" medianaX={3} medianaY={50} onEmpresaClick={vi.fn()} />,
      ),
    ).not.toThrow();
  });

  it("sin medianas no parte el plano, pero dibuja los puntos", () => {
    expect(() =>
      render(
        <CompetidoresMapaChart
          puntos={[punto("A")]}
          lente="precio"
          medianaX={null}
          medianaY={null}
          onEmpresaClick={vi.fn()}
        />,
      ),
    ).not.toThrow();
  });

  it("no revienta sin puntos", () => {
    expect(() =>
      render(
        <CompetidoresMapaChart puntos={[]} lente="precio" medianaX={null} medianaY={null} onEmpresaClick={vi.fn()} />,
      ),
    ).not.toThrow();
  });
});
