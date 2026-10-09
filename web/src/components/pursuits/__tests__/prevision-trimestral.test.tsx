/**
 * La previsión por trimestre dice qué trimestres ya pasaron: una adjudicación
 * prevista en el pasado no es «lo que viene», es una oportunidad con retraso.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { PrevisionTrimestral, trimestreDe } from "@/components/pursuits/prevision-trimestral";

afterEach(cleanup);

describe("PrevisionTrimestral", () => {
  it("marca con retraso los trimestres anteriores al actual", () => {
    render(
      <PrevisionTrimestral
        ahora={new Date(2026, 9, 9)}
        prevision={[
          { clave: "2026-Q2", etiqueta: "T2 2026", valor: 100 },
          { clave: "2026-Q4", etiqueta: "T4 2026", valor: 300 },
        ]}
      />,
    );
    expect(screen.getAllByText("con retraso")).toHaveLength(1);
    expect(screen.getByText(/la fecha prevista ya pasó/)).toBeTruthy();
  });

  it("sin trimestres pasados no hay aviso", () => {
    render(
      <PrevisionTrimestral
        ahora={new Date(2026, 9, 9)}
        prevision={[{ clave: "2026-Q4", etiqueta: "T4 2026", valor: 300 }]}
      />,
    );
    expect(screen.queryByText("con retraso")).toBeNull();
  });

  it("el trimestre de una fecha", () => {
    expect(trimestreDe(new Date(2026, 0, 1))).toBe("2026-Q1");
    expect(trimestreDe(new Date(2026, 11, 31))).toBe("2026-Q4");
  });
});
