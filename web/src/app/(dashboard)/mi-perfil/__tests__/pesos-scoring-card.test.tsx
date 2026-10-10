import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { PesosScoringCard } from "../_components/pesos-scoring-card";
import { sumWeights } from "../_lib/pesos";
import { repartirPesos } from "../_lib/reparto-pesos";

/**
 * Dos cosas se fijan aquí.
 *
 * F1.4 — la penalización por órgano que anula a menudo no es una dimensión:
 * no tiene slider ni cuenta en el 100, se enciende o se apaga (peso 0).
 *
 * Y el reparto: mover un deslizador entrega siempre un juego de pesos que suma
 * 100, sin tocar los que el usuario ha fijado. Los deslizadores se mueven con
 * el teclado, que es lo que Radix atiende en jsdom (no hay geometría para un
 * arrastre).
 */

const PESOS = {
  importe: 20,
  plazo: 15,
  competencia: 20,
  margen: 20,
  afinidad: 15,
  senal_tecnica: 10,
  organo_anula_frecuente: 8,
};

function renderCard(sobrescribe: Partial<React.ComponentProps<typeof PesosScoringCard>> = {}) {
  const props = {
    weights: PESOS,
    onWeightsChange: vi.fn(),
    onWeightChange: vi.fn(),
    onReset: vi.fn(),
    ...sobrescribe,
  };
  return { ...render(<PesosScoringCard {...props} />), props };
}

// Por etiqueta y no por rol: con seis deslizadores y sus botones, calcular el
// nombre accesible de todo el árbol en cada consulta se llevaba segundos, y
// estos tests consultan muchas veces. El rol lo fija el primer caso.
const deslizador = (nombre: string) => screen.getByLabelText(`Peso de ${nombre}`);
const botonFijar = (nombre: string) => screen.getByLabelText(`Fijar el peso de ${nombre}`);

describe("PesosScoringCard · penalización F1.4", () => {
  it("no pinta slider para la penalización y la ofrece como interruptor", () => {
    renderCard();
    expect(screen.getAllByRole("slider")).toHaveLength(6);
    expect(screen.getByRole("switch", { name: /Penalizar órganos que anulan/ })).toBeChecked();
  });

  it("apagarla la pone a 0 y encenderla le devuelve su peso", () => {
    const onWeightChange = vi.fn();
    const { rerender, props } = renderCard({ onWeightChange });
    fireEvent.click(screen.getByRole("switch", { name: /Penalizar órganos que anulan/ }));
    expect(onWeightChange).toHaveBeenCalledWith("organo_anula_frecuente", 0);

    rerender(<PesosScoringCard {...props} weights={{ ...PESOS, organo_anula_frecuente: 0 }} />);
    fireEvent.click(screen.getByRole("switch", { name: /Penalizar órganos que anulan/ }));
    expect(onWeightChange).toHaveBeenLastCalledWith("organo_anula_frecuente", 8);
  });
});

describe("PesosScoringCard · reparto", () => {
  it("subir un peso baja los demás y la suma sigue en 100", () => {
    const { props } = renderCard();

    fireEvent.keyDown(deslizador("Importe"), { key: "ArrowRight" });

    expect(props.onWeightsChange).toHaveBeenCalledTimes(1);
    const siguientes = vi.mocked(props.onWeightsChange).mock.calls[0][0];
    expect(siguientes.importe).toBe(21);
    expect(sumWeights(siguientes)).toBe(100);
    // La penalización no es parte del reparto: viaja como estaba.
    expect(siguientes.organo_anula_frecuente).toBe(8);
  });

  it("una tanda de flechas reparte como un solo movimiento, sin igualar a las demás", () => {
    // La tarjeta con estado, como en la página: cada paso vuelve como `weights`.
    let vigentes: Record<string, number> = PESOS;
    function ConEstado() {
      const [pesos, setPesos] = useState<Record<string, number>>(PESOS);
      vigentes = pesos;
      return (
        <PesosScoringCard weights={pesos} onWeightsChange={setPesos} onWeightChange={vi.fn()} onReset={vi.fn()} />
      );
    }
    render(<ConEstado />);

    // Cinco pasos bastan para separar las dos formas de repartir: encadenando
    // paso a paso, el punto de cada flecha sale siempre de la dimensión mayor
    // y a los cinco ya da 15/18/17/15/10 en vez de 14/19/19/14/9.
    const importe = deslizador("Importe");
    for (let paso = 0; paso < 5; paso += 1) {
      fireEvent.keyDown(importe, { key: "ArrowRight" });
    }

    // Lo mismo que llevar el importe a 25 de una vez: las demás conservan
    // entre sí la proporción que tenían.
    expect(vigentes).toEqual(repartirPesos(PESOS, "importe", 25));
    expect(vigentes).toMatchObject({ importe: 25, plazo: 14, competencia: 19, margen: 19, senal_tecnica: 9 });

    // Y deshacer el camino devuelve cada peso a su sitio.
    for (let paso = 0; paso < 5; paso += 1) {
      fireEvent.keyDown(importe, { key: "ArrowLeft" });
    }
    expect(vigentes).toEqual(PESOS);
  });

  it("un peso fijado no se mueve cuando cambia otro", () => {
    const { props } = renderCard();

    fireEvent.click(botonFijar("Plazo"));
    expect(screen.getByRole("button", { name: "Soltar el peso de Plazo" })).toHaveAttribute("aria-pressed", "true");
    expect(deslizador("Plazo")).toHaveAttribute("data-disabled");

    fireEvent.keyDown(deslizador("Importe"), { key: "End" });

    const siguientes = vi.mocked(props.onWeightsChange).mock.calls[0][0];
    expect(siguientes.plazo).toBe(15);
    // «Fin» pide 100; lo más que puede tomar es lo que no está fijado.
    expect(siguientes.importe).toBe(85);
    expect(sumWeights(siguientes)).toBe(100);
  });

  it("con todos los demás fijados no queda con qué compensar y lo dice", () => {
    renderCard();

    for (const nombre of ["Plazo", "Competencia", "Margen esperado", "Afinidad (palabras clave)", "Señal técnica"]) {
      fireEvent.click(botonFijar(nombre));
    }

    expect(deslizador("Importe")).toHaveAttribute("data-disabled");
    expect(screen.getByText(/no queda con qué compensar/)).toBeInTheDocument();
  });

  it("restablecer suelta lo fijado", () => {
    const { props } = renderCard();
    fireEvent.click(botonFijar("Plazo"));

    fireEvent.click(screen.getByText("Restablecer"));

    expect(props.onReset).toHaveBeenCalledTimes(1);
    expect(botonFijar("Plazo")).toHaveAttribute("aria-pressed", "false");
  });

  it("la barra dice el reparto con palabras", () => {
    renderCard();
    expect(
      screen.getByRole("img", { name: /Reparto de los 100 puntos: Importe 20, Plazo 15, Competencia 20/ }),
    ).toBeInTheDocument();
  });
});
