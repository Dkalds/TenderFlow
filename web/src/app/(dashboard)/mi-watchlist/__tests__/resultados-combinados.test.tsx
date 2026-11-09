/**
 * «Resultados combinados» no confunde un fallo con un vacío: antes cada regla
 * que fallaba devolvía `[]` y, con todas caídas, la pantalla decía que ninguna
 * licitación coincidía.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ResultadosCombinados } from "../_components/resultados-combinados";

describe("ResultadosCombinados", () => {
  it("con todas las reglas caídas enseña el error, no el vacío", () => {
    render(<ResultadosCombinados combined={undefined} loading={false} error={new Error("500")} />);
    expect(screen.getByText("No se pudieron cargar los resultados de tus reglas")).toBeInTheDocument();
    expect(screen.queryByText(/Ninguna licitación coincide/)).not.toBeInTheDocument();
  });

  it("con alguna regla caída avisa de que la lista es parcial", () => {
    render(<ResultadosCombinados combined={[]} loading={false} sinRespuesta={2} />);
    expect(screen.getByText(/2 de tus reglas no respondieron/)).toBeInTheDocument();
  });
});
