import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";

import { RadarProximas } from "@/app/(dashboard)/radar/_components/radar-proximas";
import type {
  RadarProxima,
  RadarProximasConsola,
} from "@/app/(dashboard)/radar/_hooks/use-radar-proximas";

/**
 * T5 — la bandeja «Próximas».
 *
 * El criterio de aceptación tiene tres mitades y las tres se comprueban aquí:
 * que lista lo que el backend mandó (`PRE`/`CPM`), que enseña **la fecha
 * prevista cuando existe** y que dice **«sin fecha» cuando no**.
 *
 * La cuarta cosa que se fija —y que no está en el criterio pero sí en la
 * realidad del dato— es el estado vacío: esta bandeja va a estar vacía casi
 * siempre, así que tiene que explicar por qué en vez de parecer una avería.
 */

function proxima(overrides: Partial<RadarProxima> = {}): RadarProxima {
  return {
    id_externo: "PRE-1",
    titulo: "Programa de actividades de Navidad",
    organo_contratacion: "Distrito de Chamberí",
    importe: 351641.8,
    estado: "PRE",
    fecha_publicacion: "2026-05-22",
    fecha_prevista: "2026-11-01",
    ccaa: "MAD",
    cpv: "92000000",
    url: null,
    tecnologia: null,
    ...overrides,
  };
}

function consola(overrides: Partial<RadarProximasConsola> = {}): RadarProximasConsola {
  return {
    items: [],
    total: 0,
    conFechaPrevista: 0,
    estados: ["PRE", "CPM"],
    truncadas: 0,
    isLoading: false,
    error: null,
    refetch: () => {},
    ...overrides,
  };
}

function renderBandeja(estado: Partial<RadarProximasConsola>) {
  return render(
    <TooltipProvider>
      <RadarProximas consola={consola(estado)} />
    </TooltipProvider>,
  );
}

afterEach(cleanup);

describe("RadarProximas", () => {
  it("enseña la fecha prevista cuando la fuente la publicó", () => {
    renderBandeja({ items: [proxima()], total: 1, conFechaPrevista: 1 });

    expect(screen.getByText("1 nov 2026")).toBeInTheDocument();
    expect(screen.queryByText("Sin fecha")).not.toBeInTheDocument();
  });

  it("dice «sin fecha» en vez de inventarse una", () => {
    // El caso mayoritario según el spike de T5: el expediente existe, el
    // anuncio previo está publicado, y el órgano no dijo para cuándo. Un
    // fallback a la fecha de publicación —que sí está en la fila— convertiría
    // un «no lo sé» en una afirmación.
    renderBandeja({
      items: [proxima({ fecha_prevista: null })],
      total: 1,
      conFechaPrevista: 0,
    });

    expect(screen.getByText("Sin fecha")).toBeInTheDocument();
    expect(screen.queryByText("22 may 2026")).not.toBeInTheDocument();
  });

  it("declara la cobertura con el denominador del servidor", () => {
    // «3 de 47» son dos números del universo entero, no de las tres filas
    // servidas: contarlos aquí sería fabricar analítica (ADR-014).
    renderBandeja({
      items: [proxima(), proxima({ id_externo: "PRE-2", fecha_prevista: null })],
      total: 47,
      conFechaPrevista: 3,
    });

    expect(screen.getByText("3 de 47")).toBeInTheDocument();
  });

  it("declara el universo que aplicó el servidor, no uno escrito a mano", () => {
    // Si el backend cambiara los códigos de la bandeja, la cabecera lo diría en
    // vez de seguir prometiendo los de ayer.
    // Sin filas para que el único «Anuncio previo» de la pantalla sea el de la
    // cabecera y no el badge de una fila.
    renderBandeja({ estados: ["PRE"], total: 0, conFechaPrevista: 0, items: [] });

    expect(screen.getByText("Anuncio previo")).toBeInTheDocument();
  });

  it("traduce el estado con la tabla del producto y ofrece su glosario", () => {
    renderBandeja({
      items: [proxima({ estado: "CPM", id_externo: "CPM-1" })],
      total: 1,
      conFechaPrevista: 1,
    });

    expect(screen.getByText("Consulta preliminar")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Qué es Consulta preliminar/ }),
    ).toBeInTheDocument();
  });

  it("la bandeja vacía explica qué es una próxima, no dice «sin resultados»", () => {
    renderBandeja({ items: [], total: 0, conFechaPrevista: 0 });

    expect(screen.getByText(/Ninguna compra anunciada por ahora/)).toBeInTheDocument();
    expect(screen.getByText(/es lo habitual, no un fallo de carga/i)).toBeInTheDocument();
  });

  it("con la bandeja vacía no se pinta ninguna proporción", () => {
    // «0 de 0 traen fecha prevista» es ruido con forma de dato.
    renderBandeja({ items: [], total: 0, conFechaPrevista: 0 });

    expect(screen.queryByText(/traen fecha prevista publicada/)).not.toBeInTheDocument();
  });

  it("mientras carga no afirma que no haya nada", () => {
    renderBandeja({ items: [], total: null, conFechaPrevista: null, isLoading: true });

    expect(screen.queryByText(/Ninguna compra anunciada/)).not.toBeInTheDocument();
  });

  it("un fallo de carga se declara como alerta y se puede reintentar", () => {
    renderBandeja({ items: [], total: null, error: new Error("backend caído") });

    expect(screen.getByRole("alert")).toHaveTextContent("backend caído");
    expect(screen.getByRole("button", { name: /Reintentar/ })).toBeInTheDocument();
  });

  it("cada fila lleva a su ficha completa", () => {
    // No hay inspector en esta bandeja: el detalle de un expediente sin pliego
    // vive en `/detalle`, y la fila entera es el enlace.
    renderBandeja({ items: [proxima()], total: 1, conFechaPrevista: 1 });

    expect(screen.getByRole("link")).toHaveAttribute("href", "/detalle?lic=PRE-1");
  });
});
