import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

/**
 * v148 — lo que la publicación oficial de PLACSP dice del expediente.
 *
 * El componente solo presenta lo que manda `GET /condiciones-oficiales`: no
 * suma pesos ni traduce códigos (ADR-014). Lo que se fija aquí es lo que hace
 * que el dato se lea como fuente primaria y no se confunda con la ficha del
 * pliego: su procedencia a la vista, el enlace para comprobarla, el ámbito de
 * cada requisito y que un peso sin escala publicada no se pinte como un
 * porcentaje.
 */

import { CondicionesOficialesBloque } from "@/components/pliego/condiciones-oficiales";
import type { CondicionesOficiales } from "@/hooks/use-condiciones-oficiales";

const URL_PLACSP = "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=16";

function datos(overrides: Partial<CondicionesOficiales> = {}): CondicionesOficiales {
  return {
    licitacion_id: "LIC-1",
    fuente: "placsp",
    url_publicacion: URL_PLACSP,
    actualizado: "2026-10-12T10:00:00Z",
    ambitos: [
      {
        lote_numero: null,
        lote_titulo: null,
        criterios: [
          {
            orden: 1,
            padre_orden: null,
            descripcion: "Oferta económica",
            peso: 60,
            peso_pct: 60,
            es_precio: true,
            tipo_codigo: "1",
            subtipo_codigo: null,
            nota: "Proporcional inversa a la baja",
          },
          {
            orden: 2,
            padre_orden: 1,
            descripcion: "Precio hora perfil senior",
            peso: 70,
            peso_pct: null,
            es_precio: true,
            tipo_codigo: null,
            subtipo_codigo: null,
            nota: null,
          },
          {
            orden: 3,
            padre_orden: null,
            descripcion: "Memoria técnica",
            peso: 40,
            peso_pct: 40,
            es_precio: false,
            tipo_codigo: "2",
            subtipo_codigo: null,
            nota: null,
          },
        ],
        garantias: [
          {
            orden: 1,
            tipo_codigo: "2",
            porcentaje: 5,
            importe: null,
            moneda: null,
            descripcion: null,
          },
        ],
        solvencia: [
          {
            orden: 1,
            clase: "economica",
            tipo_codigo: "1",
            descripcion: "Volumen anual de negocios",
            umbral_importe: 480000,
            moneda: "EUR",
          },
          {
            orden: 2,
            clase: "clasificacion",
            tipo_codigo: "V2",
            descripcion: "Servicios TIC",
            umbral_importe: null,
            moneda: null,
          },
        ],
      },
      {
        lote_numero: "2",
        lote_titulo: "Soporte Oracle",
        criterios: [
          {
            orden: 1,
            padre_orden: null,
            descripcion: "Precio",
            peso: 70,
            peso_pct: null,
            es_precio: true,
            tipo_codigo: null,
            subtipo_codigo: null,
            nota: null,
          },
        ],
        garantias: [
          {
            orden: 1,
            tipo_codigo: "1",
            porcentaje: null,
            importe: 4800,
            moneda: "EUR",
            descripcion: null,
          },
        ],
        solvencia: [],
      },
    ],
    ...overrides,
  };
}

describe("CondicionesOficialesBloque", () => {
  it("declara la procedencia y enlaza la publicación para comprobarla", () => {
    render(<CondicionesOficialesBloque datos={datos()} licitacionId="LIC-1" />);

    expect(screen.getByText("Publicación oficial (PLACSP)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ver la publicación en PLACSP/ })).toHaveAttribute(
      "href",
      URL_PLACSP,
    );
    expect(screen.getByText(/Leída el/)).toBeInTheDocument();
  });

  it("separa el expediente de cada lote, con su título", () => {
    render(<CondicionesOficialesBloque datos={datos()} licitacionId="LIC-1" />);

    const expediente = screen.getByRole("region", { name: "Expediente" });
    const lote = screen.getByRole("region", { name: "Lote 2 · Soporte Oracle" });
    expect(within(expediente).getByText("Oferta económica")).toBeInTheDocument();
    expect(within(lote).getByText(/4\.?800\s€/)).toBeInTheDocument();
  });

  it("pinta el peso como porcentaje solo cuando la escala está publicada", () => {
    render(<CondicionesOficialesBloque datos={datos()} licitacionId="LIC-1" />);

    const expediente = screen.getByRole("region", { name: "Expediente" });
    expect(within(expediente).getByText("60%")).toBeInTheDocument();
    // El subcriterio reparte el peso de su padre: se enseña tal cual, sin «%».
    expect(within(expediente).getByText("Peso publicado: 70")).toBeInTheDocument();
    const lote = screen.getByRole("region", { name: "Lote 2 · Soporte Oracle" });
    expect(within(lote).getByText("Peso publicado: 70")).toBeInTheDocument();
    expect(within(lote).queryByText("70%")).not.toBeInTheDocument();
  });

  it("enseña garantías, solvencia con su umbral y la clasificación con su código", () => {
    render(<CondicionesOficialesBloque datos={datos()} licitacionId="LIC-1" />);

    const expediente = screen.getByRole("region", { name: "Expediente" });
    expect(within(expediente).getByText("5%")).toBeInTheDocument();
    expect(within(expediente).getByText("Volumen anual de negocios")).toBeInTheDocument();
    expect(within(expediente).getByText(/Umbral 480\.000/)).toBeInTheDocument();
    expect(within(expediente).getByText("V2 · Servicios TIC")).toBeInTheDocument();
    expect(within(expediente).getByText("Proporcional inversa a la baja")).toBeInTheDocument();
  });

  it("dice cuándo la publicación es la del expediente original", () => {
    render(
      <CondicionesOficialesBloque datos={datos({ licitacion_id: "PLACSP-1" })} licitacionId="TED-1" />,
    );

    expect(screen.getByText(/publicación oficial del expediente original PLACSP-1/)).toBeInTheDocument();
  });

  it("sin ámbitos no pinta nada", () => {
    const { container } = render(
      <CondicionesOficialesBloque datos={datos({ ambitos: [] })} licitacionId="LIC-1" />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
