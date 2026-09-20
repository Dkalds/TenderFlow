/**
 * F3.5 — los cortes por procedimiento y tamaño del perfil de competidor.
 *
 * Lo que fija: cada celda enseña su `n`; por debajo del mínimo no se pinta una
 * media (se dice «menos de N»); la baja llega en tanto por uno y se pinta en %.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

import { CompanyCortes } from "../company-cortes";

afterEach(cleanup);

describe("CompanyCortes", () => {
  it("pinta n y baja por celda, y no inventa la media bajo el mínimo", () => {
    render(
      <CompanyCortes
        porProcedimiento={[
          { clave: "Abierto", n: 6, baja_media: 0.2, importe_total: 480000 },
          { clave: "Negociado sin publicidad", n: 2, baja_media: null, importe_total: null },
        ]}
        porTramo={[{ clave: "60k-140k", n: 6, baja_media: 0.2, importe_total: 480000 }]}
        minimo={5}
      />,
    );

    const procedimiento = screen.getByRole("table", { name: "Por procedimiento" });
    const abierto = within(procedimiento).getByText("Abierto").closest("tr")!;
    expect(abierto).toHaveTextContent("6");
    expect(abierto).toHaveTextContent("20,0%");
    const negociado = within(procedimiento).getByText("Negociado sin publicidad").closest("tr")!;
    expect(negociado).toHaveTextContent("menos de 5");

    expect(screen.getByRole("table", { name: "Por tamaño" })).toHaveTextContent("60k-140k");
  });

  it("un corte vacío lo dice", () => {
    render(<CompanyCortes porProcedimiento={[]} porTramo={[]} minimo={5} />);
    expect(screen.getAllByText("Sin datos para este corte")).toHaveLength(2);
  });
});
