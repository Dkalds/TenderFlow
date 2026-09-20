/**
 * F2.2 — simulador de puntuación.
 *
 * Se fija lo que el plan exige a la pantalla: sin fórmula no hay cifras sino
 * el motivo; con fórmula, los puntos y el hueco son los de la API (nada se
 * calcula aquí); la baja del rival puede salir del p90 de la predicción; y la
 * telemetría sale una vez por simulación, con el tipo de fórmula.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

import { registrarEvento } from "@/lib/analytics";
import { callUrl } from "@/hooks/__tests__/fetch-call";
import {
  conTarifas,
  parsearBajaPct,
  SimuladorPuntuacion,
} from "@/components/pliego/simulador-puntuacion";
import type { TenderFactSheetRecord } from "@/hooks/use-tender-fact-sheet";
import { fetchPorRuta, renderConQuery } from "./pliego-render";

const REFERENCIA = {
  licitacion_id: "LIC-1",
  formula_tipo: "proporcional_inversa",
  puntos_precio: 45,
  puntos_precio_origen: "pliego",
  escenarios: [
    { baja: 0.05, puntos: 9, temeraria: false },
    { baja: 0.25, puntos: 45, temeraria: true },
  ],
  hueco_vs_referencia: null,
  baja_referencia: null,
  sin_calculo: null,
};

const PROPIA = {
  ...REFERENCIA,
  escenarios: [{ baja: 0.12, puntos: 38, temeraria: false }],
  hueco_vs_referencia: -7,
  baja_referencia: 0.18,
};

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("conTarifas (F2.4)", () => {
  const ficha = (rate_cards: unknown[]) =>
    ({ facts: { rate_cards } }) as unknown as TenderFactSheetRecord;

  it("sólo dice «si» con tarifa y horas, que es cuando el backend puede dar margen", () => {
    expect(conTarifas(ficha([{ role: "A", max_rate_eur_hour: 60, estimated_hours: 100 }]))).toBe("si");
    expect(conTarifas(ficha([{ role: "A", max_rate_eur_hour: 60, estimated_hours: null }]))).toBe("no");
    expect(conTarifas(ficha([]))).toBe("no");
  });

  it("sin ficha cargada no se sabe y no se afirma nada", () => {
    expect(conTarifas(undefined)).toBeUndefined();
  });
});

describe("parsearBajaPct", () => {
  it.each([
    ["12", 0.12],
    ["12,5", 0.125],
    ["12.5 %", 0.125],
    ["0", 0],
  ])("«%s» → %s", (texto, esperado) => {
    expect(parsearBajaPct(texto)).toBe(esperado);
  });

  it.each(["", "abc", "-1", "101"])("«%s» no es una baja", (texto) => {
    expect(parsearBajaPct(texto)).toBeNull();
  });
});

describe("SimuladorPuntuacion", () => {
  it("sin fórmula en el pliego dice por qué y no enseña cifras", async () => {
    fetchPorRuta(
      [/simulador/, { licitacion_id: "LIC-1", escenarios: [], sin_calculo: "sin_formula", puntos_precio_origen: "desconocido" }],
      [/prediccion-baja/, {}, 404],
    );
    renderConQuery(<SimuladorPuntuacion licitacionId="LIC-1" />);

    expect(await screen.findByText(/Fórmula no encontrada en el pliego/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Simular" })).not.toBeInTheDocument();
  });

  it("pinta los escenarios de la API, con el origen de los puntos y la temeridad", async () => {
    fetchPorRuta([/simulador/, REFERENCIA], [/prediccion-baja/, {}, 404]);
    renderConQuery(<SimuladorPuntuacion licitacionId="LIC-1" />);

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByText(/reparte 45 puntos/)).toHaveTextContent("leídos del pliego");
    expect(screen.getByText("Proporcional inversa")).toBeInTheDocument();
    expect(screen.getByText("Temeraria")).toBeInTheDocument();
  });

  it("simula la baja propia contra la del rival y cuenta el uso una sola vez", async () => {
    const fetch = fetchPorRuta(
      [/simulador\?baja=0\.12/, PROPIA],
      [/simulador/, REFERENCIA],
      [/prediccion-baja/, { licitacion_id: "LIC-1", p10: 0.08, p50: 0.12, p90: 0.18 }],
    );
    renderConQuery(<SimuladorPuntuacion licitacionId="LIC-1" />);
    await screen.findByRole("table");

    fireEvent.change(screen.getByLabelText("Tu baja (%)"), { target: { value: "12" } });
    // La baja del rival sale del p90 de la predicción con un clic.
    fireEvent.click(await screen.findByRole("button", { name: /p90 de la baja esperada/ }));
    expect(screen.getByLabelText("Baja del rival (%)")).toHaveValue("18");
    fireEvent.click(screen.getByRole("button", { name: "Simular" }));

    expect(await screen.findByText(/Te faltan/)).toHaveTextContent(
      "Te faltan 7 puntos de precio frente al rival",
    );
    expect(screen.getByText(/Con una baja del 12,0% obtienes/)).toBeInTheDocument();
    const pedida = fetch.mock.calls.map((c) => callUrl(c)).find((u) => u.includes("baja=0.12"));
    expect(pedida).toBe("/api/v1/licitaciones/LIC-1/simulador?baja=0.12&baja_referencia=0.18");

    await waitFor(() =>
      expect(registrarEvento).toHaveBeenCalledWith("simulador_usado", {
        formula_tipo: "proporcional_inversa",
      }),
    );
    expect(registrarEvento).toHaveBeenCalledTimes(1);
  });

  it("una baja fuera de rango no se envía y lo dice", async () => {
    fetchPorRuta([/simulador/, REFERENCIA], [/prediccion-baja/, {}, 404]);
    renderConQuery(<SimuladorPuntuacion licitacionId="LIC-1" />);
    await screen.findByRole("table");

    fireEvent.change(screen.getByLabelText("Tu baja (%)"), { target: { value: "150" } });

    expect(screen.getByRole("alert")).toHaveTextContent("entre 0 y 100");
    expect(screen.getByRole("button", { name: "Simular" })).toBeDisabled();
  });
});
