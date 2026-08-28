import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { LicitacionPublica } from "@/lib/publico-api";
import { ListadoLicitaciones } from "../listado-licitaciones";

/**
 * El listado de los hubs es la primera pantalla del embudo orgánico, y durante
 * meses mintió en dos campos a la vez: enseñaba el código interno del estado
 * («AGR», «EJEC») como si fuera texto para humanos, y prometía «Hasta el
 * <fecha>» sobre plazos vencidos hacía meses. Estos tests fijan las dos
 * traducciones —no la maquetación de los chips— con el reloj congelado, porque
 * un test que dependa del día en que se ejecuta deja de proteger nada.
 */
function anuncio(extra: Partial<LicitacionPublica> = {}): LicitacionPublica {
  return {
    ref: "abc123",
    titulo: "Servicios de mantenimiento de redes",
    expediente: "EXP/2026/1",
    fuente: "placsp",
    ccaa: "Cataluña",
    ...extra,
  };
}

describe("ListadoLicitaciones", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-28T10:00:00+02:00"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("traduce el estado en vez de publicar el código de la fuente", () => {
    render(<ListadoLicitaciones licitaciones={[anuncio({ estado: "AGR" })]} jsonLdNombre="Hub" />);

    expect(screen.getByText("Publicación agregada")).toBeInTheDocument();
    expect(screen.queryByText("AGR")).not.toBeInTheDocument();
  });

  it("no presenta como vivo un plazo que ya venció", () => {
    render(
      <ListadoLicitaciones
        licitaciones={[anuncio({ estado: "AGR", fecha_limite: "2026-03-03" })]}
        jsonLdNombre="Hub"
      />,
    );

    expect(screen.getByText("Plazo cerrado el 3 mar 2026")).toBeInTheDocument();
    expect(screen.queryByText(/Hasta el/)).not.toBeInTheDocument();
  });

  it("sigue anunciando como abierto el plazo que no ha vencido", () => {
    render(<ListadoLicitaciones licitaciones={[anuncio({ fecha_limite: "2026-12-31" })]} jsonLdNombre="Hub" />);

    expect(screen.getByText("Hasta el 31 dic 2026")).toBeInTheDocument();
    expect(screen.queryByText(/Plazo cerrado/)).not.toBeInTheDocument();
  });

  it("no excluye del listado el expediente cerrado", () => {
    // Los expedientes vencidos conservan valor de búsqueda: el arreglo es de
    // presentación, no un filtro. Si esta fila desapareciera, se estaría
    // tirando índice a cambio de nada.
    render(
      <ListadoLicitaciones
        licitaciones={[anuncio({ estado: "AGR", fecha_limite: "2026-03-03" })]}
        jsonLdNombre="Hub"
      />,
    );

    expect(screen.getByRole("heading", { name: "Servicios de mantenimiento de redes" })).toBeInTheDocument();
  });

  it("omite el chip de plazo cuando el anuncio no trae fecha límite", () => {
    render(<ListadoLicitaciones licitaciones={[anuncio()]} jsonLdNombre="Hub" />);

    expect(screen.queryByText(/Hasta el/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Plazo cerrado/)).not.toBeInTheDocument();
  });
});
