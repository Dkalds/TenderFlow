/**
 * La vista de UTE montada entera sobre una respuesta de ejemplo.
 *
 * Fija el contrato con la API: la respuesta está tipada desde el esquema
 * generado y cada campo se busca en pantalla. La pantalla llegó a pintar una
 * evolución vacía y una comparativa sin recuentos porque leía `periodo` y
 * `count` donde la API manda `period` y `contratos`, y `contratos` donde manda
 * `count`; con tipos escritos a mano, eso compilaba.
 *
 * Fija además lo que la red sólo da al ratón y la lista da al teclado: elegir
 * una empresa cambia la lista por la de sus socios, desde cualquiera de las dos.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Schemas } from "@/lib/api-types";
import { formatCompactCurrency, formatCurrency, formatMonth } from "@/lib/utils";

const { useFilteredQuery } = vi.hoisted(() => ({ useFilteredQuery: vi.fn() }));
vi.mock("@/hooks/use-filtered-query", () => ({ useFilteredQuery }));

// La exportación no es el sujeto: lee el ámbito y abre un menú. Aquí basta con
// saber que la cabecera la monta con su rótulo.
vi.mock("@/components/export-popover", () => ({
  ExportPopover: ({ label }: { label: string }) => React.createElement("button", { type: "button" }, label),
}));

import UtesView from "../_components/utes-view";
import { RED_ALTO, RED_ANCHO } from "../_hooks/utes-red";

type UTEResult = Schemas["UTEResult"];

const RESPUESTA: UTEResult = {
  kpis: {
    total_ute: 148,
    importe_ute: 282_500_000,
    ticket_medio_ute: 1_900_000,
    ticket_medio_individual: 560_000,
    empresas_distintas: 61,
  },
  top_miembros: [
    { nombre: "UTE ACME - BETA", count: 9, importe: 31_200_000 },
    { nombre: "UTE DELTA - EPSILON", count: 5, importe: 2_500_000 },
    { nombre: "UTE BETA - GAMMA", count: 3, importe: 900_000 },
  ],
  socios_frecuentes: [
    { empresa_a: "ACME", empresa_b: "BETA", contratos: 9, importe: 31_200_000 },
    { empresa_a: "BETA", empresa_b: "GAMMA", contratos: 3, importe: 900_000 },
    { empresa_a: "DELTA", empresa_b: "EPSILON", contratos: 5, importe: 2_500_000 },
  ],
  evolucion: [
    { period: "2025-12", contratos: 4, importe: 6_000_000 },
    { period: "2026-01", contratos: 7, importe: 12_300_000 },
  ],
  tabla_comparativa: {
    ute: { count: 148, importe_medio: 1_900_000, importe_total: 282_500_000 },
    individual: { count: 978, importe_medio: 560_000, importe_total: 547_700_000 },
  },
};

const SIN_UTE: UTEResult = {
  kpis: {
    total_ute: 0,
    importe_ute: 0,
    ticket_medio_ute: 0,
    ticket_medio_individual: 560_000,
    empresas_distintas: 0,
  },
  top_miembros: [],
  socios_frecuentes: [],
  evolucion: [],
  tabla_comparativa: {
    ute: { count: 0, importe_medio: 0, importe_total: 0 },
    individual: { count: 978, importe_medio: 560_000, importe_total: 547_700_000 },
  },
};

/**
 * Los importes llevan un espacio duro antes del «€» y testing-library compara
 * contra el texto con los espacios ya normalizados.
 */
const plano = (texto: string) => texto.replace(/\s+/g, " ");

function montar(consulta: { data?: UTEResult; isLoading?: boolean; error?: unknown; refetch?: () => void }) {
  useFilteredQuery.mockReturnValue({ data: undefined, isLoading: false, error: null, refetch: vi.fn(), ...consulta });
  // `TooltipProvider`: el nombre de cada UTE abre un `Tooltip` al pasar por él.
  return render(
    <TooltipProvider>
      <UtesView />
    </TooltipProvider>,
  );
}

const tituloDeLista = (nombre: string) => screen.queryByRole("heading", { level: 3, name: nombre });

afterEach(() => {
  cleanup();
  useFilteredQuery.mockReset();
});

describe("UTE — el contrato de la API llega a pantalla", () => {
  it("pide las UTE del ámbito a su ruta", () => {
    montar({ data: RESPUESTA });
    expect(useFilteredQuery).toHaveBeenCalledWith(["analytics", "utes"], "/api/v1/analytics/utes", expect.anything());
  });

  it("titula con los dos importes medios, dichos tal cual", () => {
    montar({ data: RESPUESTA });

    expect(screen.getByRole("heading", { level: 1, name: "UTE" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      plano(
        `En UTE, el contrato medio es de ${formatCompactCurrency(1_900_000)}; en solitario, de ${formatCompactCurrency(560_000)}`,
      ),
    );
    expect(
      screen.getByText(plano(`148 adjudicaciones a UTE · ${formatCurrency(282_500_000)}.`), { exact: false }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exportar UTE" })).toBeInTheDocument();
  });

  it("compara cada cifra con lo adjudicado en solitario (`tabla_comparativa.individual`)", () => {
    montar({ data: RESPUESTA });

    expect(screen.getByText("Adjudicaciones a UTE")).toBeInTheDocument();
    expect(screen.getByText("frente a 978 en solitario")).toBeInTheDocument();
    expect(screen.getByText(plano(`frente a ${formatCurrency(547_700_000)} en solitario`))).toBeInTheDocument();
    // El recuento de nombres de UTE no es un número de empresas: no se enseña.
    expect(screen.queryByText("Empresas distintas")).not.toBeInTheDocument();
  });

  it("pinta el importe medio de las dos formas, cada uno con su cifra", () => {
    montar({ data: RESPUESTA });

    const celda = screen.getByText("Importe medio por contrato").parentElement as HTMLElement;
    expect(within(celda).getByText("En UTE").nextElementSibling).toHaveTextContent(plano(formatCurrency(1_900_000)));
    expect(within(celda).getByText("En solitario").nextElementSibling).toHaveTextContent(
      plano(formatCurrency(560_000)),
    );
  });

  it("pinta la evolución mes a mes (`evolucion[].period` y `contratos`)", () => {
    montar({ data: RESPUESTA });

    const tabla = screen.getByRole("table", { name: "UTE adjudicadas e importe, por mes" });
    const celdasDe = (period: string) => {
      const fila = within(tabla).getByRole("rowheader", { name: formatMonth(period, true) }).closest("tr");
      return within(fila as HTMLElement)
        .getAllByRole("cell")
        .map((celda) => plano(celda.textContent ?? ""));
    };
    expect(celdasDe("2025-12")).toEqual(["4", plano(formatCurrency(6_000_000))]);
    expect(celdasDe("2026-01")).toEqual(["7", plano(formatCurrency(12_300_000))]);
    // Cada gráfico dice su escala: el mes con más UTE es el de 7.
    expect(screen.getByText("máximo 7 en un mes")).toBeInTheDocument();
  });

  it("lista las UTE con más adjudicaciones y deja buscar entre ellas", () => {
    montar({ data: RESPUESTA });

    const ranking = screen.getByRole("columnheader", { name: "Adjudicaciones" }).closest("table") as HTMLElement;
    expect(within(ranking).getAllByRole("row")).toHaveLength(1 + 3);
    expect(within(ranking).getByText("UTE ACME - BETA")).toBeInTheDocument();
    expect(screen.getByText(/^3 de 3 UTE\./)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Buscar UTE" }), { target: { value: "épsilon" } });

    expect(within(ranking).getByText("UTE DELTA - EPSILON")).toBeInTheDocument();
    expect(within(ranking).queryByText("UTE ACME - BETA")).not.toBeInTheDocument();
    expect(screen.getByText(/^1 de 3 UTE\./)).toBeInTheDocument();
  });
});

describe("UTE — la red y su lista", () => {
  it("dibuja un nodo por empresa y deja el dibujo fuera del lector de pantalla", () => {
    const { container } = montar({ data: RESPUESTA });

    const dibujo = container.querySelector(`svg[viewBox="0 0 ${RED_ANCHO} ${RED_ALTO}"]`);
    expect(dibujo).toHaveAttribute("aria-hidden", "true");
    expect(dibujo?.querySelectorAll("[data-nodo]")).toHaveLength(5);
    expect(dibujo?.querySelectorAll("line")).toHaveLength(3);
    expect(screen.getByText(/^Los 3 pares con más UTE del ámbito, no todos\./)).toBeInTheDocument();
  });

  it("sin empresa elegida lista los pares, del más repetido al menos", () => {
    montar({ data: RESPUESTA });

    expect(tituloDeLista("Las alianzas más repetidas")).toBeInTheDocument();
    const filas = screen.getAllByRole("button", { name: /^Ver las alianzas de / });
    expect(filas.map((fila) => fila.textContent)).toEqual([
      expect.stringContaining("ACME + BETA"),
      expect.stringContaining("DELTA + EPSILON"),
      expect.stringContaining("BETA + GAMMA"),
    ]);
    expect(filas[0]).toHaveTextContent("9 UTE");
  });

  it("elegir una empresa en la lista la cambia por la de sus socios", () => {
    montar({ data: RESPUESTA });

    fireEvent.click(screen.getByRole("button", { name: /BETA \+ GAMMA/ }));

    expect(tituloDeLista("Con quién se alía BETA")).toBeInTheDocument();
    expect(tituloDeLista("Las alianzas más repetidas")).not.toBeInTheDocument();
    const filas = screen.getAllByRole("button", { name: /^Ver las alianzas de / });
    expect(filas.map((fila) => fila.textContent)).toEqual([
      expect.stringContaining("ACME"),
      expect.stringContaining("GAMMA"),
    ]);
    expect(screen.queryByRole("button", { name: /DELTA \+ EPSILON/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Ver todas" }));

    expect(tituloDeLista("Las alianzas más repetidas")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /DELTA \+ EPSILON/ })).toBeInTheDocument();
  });

  it("pulsar un nodo lo elige, marca sus alianzas con su número de UTE y, a la segunda, lo suelta", () => {
    const { container } = montar({ data: RESPUESTA });
    const nodo = (nombre: string) => container.querySelector(`[data-nodo="${nombre}"]`) as Element;

    fireEvent.click(nodo("DELTA"));

    expect(tituloDeLista("Con quién se alía DELTA")).toBeInTheDocument();
    expect(nodo("DELTA")).toHaveAttribute("data-estado", "elegido");
    expect(nodo("EPSILON")).toHaveAttribute("data-estado", "socio");
    expect(nodo("ACME")).toHaveAttribute("data-estado", "atenuado");
    // La pastilla a mitad de línea: las 5 UTE de DELTA con EPSILON.
    const pastillas = [...container.querySelectorAll("svg[aria-hidden] g:not([data-nodo]) > text")];
    expect(pastillas.map((p) => p.textContent)).toEqual(["5"]);

    fireEvent.click(nodo("DELTA"));

    expect(tituloDeLista("Las alianzas más repetidas")).toBeInTheDocument();
    expect(nodo("DELTA")).toHaveAttribute("data-estado", "normal");
  });
});

describe("UTE — sin dato", () => {
  it("sin UTE en el ámbito cada panel lo dice, y el titular no afirma un importe medio de cero", () => {
    montar({ data: SIN_UTE });

    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Con quién se alía cada competidor para ganar",
    );
    expect(screen.getByText("Ningún par de socios")).toBeInTheDocument();
    expect(
      screen.getByText("Ninguna pareja de empresas ha firmado una UTE junta en el ámbito actual."),
    ).toBeInTheDocument();
    expect(screen.getByText("Ninguna alianza que listar")).toBeInTheDocument();
    expect(screen.getByText("Ningún mes con UTE")).toBeInTheDocument();
    expect(screen.getByText("Ninguna UTE")).toBeInTheDocument();
    // En solitario sí hay contratos: su barra y su cifra siguen ahí.
    const celda = screen.getByText("Importe medio por contrato").parentElement as HTMLElement;
    expect(within(celda).getByText("En UTE").nextElementSibling).toHaveTextContent("—");
    expect(within(celda).getByText("En solitario").nextElementSibling).toHaveTextContent(
      plano(formatCurrency(560_000)),
    );
  });

  it("mientras carga se queda en la pregunta de la vista, sin cifras a medias", () => {
    montar({ isLoading: true });

    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Con quién se alía cada competidor para ganar",
    );
    expect(screen.queryByText(/en solitario/)).not.toBeInTheDocument();
    expect(screen.queryByText("Ningún par de socios")).not.toBeInTheDocument();
  });

  it("si la petición falla lo dice y deja reintentar", () => {
    const refetch = vi.fn();
    montar({ error: new Error("sin respuesta"), refetch });

    expect(screen.getByRole("alert")).toHaveTextContent("No se pudieron cargar las UTE");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
