import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScoreDesglose } from "@/components/score-desglose";

/**
 * S2.4 — el desglose dice contra qué se midió la afinidad.
 *
 * El resto del componente (orden de dimensiones, barras, avisos) ya lo
 * ejercita el test de la página del Radar; aquí se fija sólo lo que añade
 * `afinidad_origen`, que es lo que el plan pide que el Radar enseñe.
 */

const DESGLOSE = {
  importe: 18.4,
  plazo: 15,
  competencia: 12.5,
  margen: 10,
  afinidad: 7.5,
  senal_tecnica: 5,
};

describe("ScoreDesglose · origen de la afinidad", () => {
  it("dice cuándo la afinidad viene de la capacidad de la organización", () => {
    render(<ScoreDesglose desglose={DESGLOSE} afinidadOrigen="organizacion" />);
    expect(screen.getByText(/capacidad declarada de tu organización/i)).toBeInTheDocument();
  });

  it("dice cuándo viene del perfil personal", () => {
    render(<ScoreDesglose desglose={DESGLOSE} afinidadOrigen="perfil" />);
    expect(screen.getByText(/tu perfil personal/i)).toBeInTheDocument();
  });

  it("explica el caso sin perfil ni capacidad en vez de callarlo", () => {
    // Sin origen declarado la fila «Afinidad» ni aparece (el peso se
    // redistribuye en backend). El hueco silencioso se lee como una avería.
    const { afinidad: _afinidad, ...sinAfinidad } = DESGLOSE;
    render(<ScoreDesglose desglose={sinAfinidad} afinidadOrigen="ninguno" />);
    expect(screen.queryByText("Afinidad")).not.toBeInTheDocument();
    expect(screen.getByText(/no mide encaje/i)).toBeInTheDocument();
  });

  it("no pinta nada si el backend no declaró el origen", () => {
    const { container } = render(<ScoreDesglose desglose={DESGLOSE} />);
    expect(container.querySelector('[data-slot="afinidad-origen"]')).toBeNull();
  });

  it("no inventa procedencia ante un valor que no conoce", () => {
    // Contrato aditivo: si el backend añade un origen nuevo, el desglose
    // calla en vez de rotularlo mal. No hace falta desplegar los dos a la vez.
    const { container } = render(
      <ScoreDesglose desglose={DESGLOSE} afinidadOrigen="federacion_de_gremios" />,
    );
    expect(container.querySelector('[data-slot="afinidad-origen"]')).toBeNull();
  });
});
