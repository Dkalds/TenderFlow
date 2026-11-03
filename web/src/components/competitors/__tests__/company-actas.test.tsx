/**
 * Dónde puntúa un competidor según las actas de la mesa.
 *
 * Lo que fija: bajo el mínimo de actas no se pinta una media, se dice; la
 * lectura compara las dos medias que da el backend y solo cuando las dos
 * existen; y las exclusiones se cuentan.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { CompanyActas } from "../company-actas";
import { lecturaActas, type CompanyActaScores } from "../company-profile-types";

afterEach(cleanup);

function acta(precio: number | null, tecnica: number | null, extra: Partial<CompanyActaScores> = {}): CompanyActaScores {
  return {
    actas: 4,
    excluida: 0,
    min_actas: 3,
    precio: { actas: precio == null ? 2 : 4, pct_medio: precio },
    tecnica: { actas: tecnica == null ? 2 : 4, pct_medio: tecnica },
    ...extra,
  };
}

describe("lecturaActas", () => {
  it("dice con qué compite cuando una media pesa claramente más", () => {
    expect(lecturaActas(acta(95, 50))).toMatch(/oferta económica/);
    expect(lecturaActas(acta(40, 90))).toMatch(/propuesta técnica/);
    expect(lecturaActas(acta(70, 64))).toBe("Puntúa parecido en precio y en lo técnico.");
  });

  it("sin las dos medias no compara", () => {
    expect(lecturaActas(acta(95, null))).toBeNull();
  });
});

describe("CompanyActas", () => {
  it("pinta las medias, las actas y la lectura", () => {
    render(<CompanyActas acta={acta(95, 50, { excluida: 1 })} />);

    expect(screen.getByText("Puntos de precio").closest("div")?.parentElement).toHaveTextContent("95");
    expect(screen.getByText("Excluida en 1")).toBeInTheDocument();
    expect(screen.getByText(/oferta económica/)).toBeInTheDocument();
  });

  it("bajo el mínimo no inventa la media", () => {
    render(<CompanyActas acta={acta(null, null)} />);

    expect(screen.getAllByText("Sin datos suficientes: 2 actas")).toHaveLength(2);
    expect(screen.queryByText(/compite/)).toBeNull();
  });
});
