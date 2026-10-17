import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { posicionEnReloj, Proporcion, PuntosUnidad, RelojCierre, TOPE_PUNTOS } from "../cifras-graficos";

describe("PuntosUnidad", () => {
  const cuadrados = (container: HTMLElement) => container.querySelectorAll(".h-2.w-2");

  it("pinta un cuadrado por elemento contado", () => {
    const { container } = render(<PuntosUnidad n={3} />);
    expect(cuadrados(container)).toHaveLength(3);
  });

  it("pasado el tope, dice el resto en texto en vez de desbordar la celda", () => {
    const { container } = render(<PuntosUnidad n={TOPE_PUNTOS + 7} />);
    expect(cuadrados(container)).toHaveLength(TOPE_PUNTOS);
    expect(container).toHaveTextContent("+7");
  });

  it("con cero deja el carril en vez de desaparecer, y es decorativo", () => {
    const { container } = render(<PuntosUnidad n={0} />);
    expect(cuadrados(container)).toHaveLength(0);
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
    expect(container.firstElementChild?.childElementCount).toBe(1);
  });
});

describe("RelojCierre", () => {
  it("coloca cada plazo sobre las 48 horas y acota lo que se sale", () => {
    expect(posicionEnReloj(0)).toBe(0);
    expect(posicionEnReloj(12)).toBe(25);
    expect(posicionEnReloj(48)).toBe(100);
    expect(posicionEnReloj(60)).toBe(100);
  });

  it("un punto por expediente, rojo en las últimas 24 horas", () => {
    const { container } = render(<RelojCierre horas={[3, 20, 30]} />);
    const puntos = [...container.querySelectorAll("circle")];
    expect(puntos.map((punto) => punto.getAttribute("cx"))).toEqual(["6.25%", "41.66666666666667%", "62.5%"]);
    expect(puntos.map((punto) => punto.classList.contains("fill-destructive"))).toEqual([true, true, false]);
  });
});

describe("Proporcion", () => {
  it("escribe la parte del total junto a la barra", () => {
    const { container } = render(<Proporcion parte={28250} total={124760} de="del ámbito" />);
    expect(container).toHaveTextContent("22,6% del ámbito");
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("una parte diminuta no se redondea a cero, y una nula sí es cero", () => {
    expect(render(<Proporcion parte={12} total={42100} de="de las activas" />).container).toHaveTextContent(
      "<0,1% de las activas",
    );
    expect(render(<Proporcion parte={0} total={100} de="del ámbito" />).container).toHaveTextContent("0,0% del ámbito");
  });
});
