/**
 * Competencia esperada: el bloque compartido de Radar, Detalle y oportunidad.
 *
 * El bloque al que sustituye pintaba los adjudicatarios del órgano entero con
 * un porcentaje sobre un denominador equivocado. Lo que se fija aquí es lo que
 * hace que el nuevo responda a la licitación y no lo invente:
 *
 * - pregunta por el expediente con la organización activa (la respuesta saca a
 *   la propia organización de los rivales), y no antes de saber cuál es;
 * - cada cifra va con su universo, su ventana y su `n`, tal como llegan;
 * - sin dato se dice por qué, y un fallo no se lee como «sin rivales».
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { CompetenciaEsperada } from "@/lib/api-types";

const { fetchWithAuth, organizacion } = vi.hoisted(() => ({
  fetchWithAuth: vi.fn(),
  organizacion: { id: 21 as number | null | undefined },
}));

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  fetchWithAuth,
}));
vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => organizacion.id,
  organizacionResuelta: (id: number | null | undefined) => id !== undefined,
}));

import { CompetenciaEsperadaBlock, describirSegmento } from "@/components/competencia-esperada";
import { ApiError } from "@/lib/api-client";

const ID = "PA-S 2026/000058";

const COMPLETA: CompetenciaEsperada = {
  licitacion_id: ID,
  organo: "Ayuntamiento de Pruebas",
  cpv4: "7226",
  ccaa: "Madrid",
  ofertas: {
    ventana_meses: 24,
    estimacion: 3,
    estimacion_nivel: "organo_cpv4",
    organo_cpv4: {
      nivel: "organo_cpv4",
      media: 2.83,
      expedientes: 6,
      adjudicados: 8,
      pct_oferta_unica: 16.7,
      bandas: [
        { banda: "1", expedientes: 1, pct: 16.7 },
        { banda: "2-4", expedientes: 4, pct: 66.7 },
        { banda: "5+", expedientes: 1, pct: 16.7 },
      ],
    },
    cpv4: {
      nivel: "cpv4",
      media: 3.88,
      expedientes: 8,
      adjudicados: 8,
      pct_oferta_unica: 12.5,
      bandas: [],
    },
    media_global: null,
    sin_datos: null,
  },
  incumbente: {
    licitacion_id: "H0",
    titulo: "Mantenimiento de la plataforma SAP",
    adjudicatario: "ALFA SA",
    empresa_id: 101,
    importe_adjudicado: 330000,
    baja_pct: 13.16,
    fecha_adjudicacion: "2022-03-14",
    es_propia: false,
    metodo: "fts",
  },
  rivales: {
    ventana_meses: 36,
    nivel: "organo_cpv4",
    expedientes: 6,
    importe_total: 741000,
    muestra_suficiente: true,
    items: [
      {
        nombre: "ALFA CONSULTORÍA SA",
        empresa_id: 101,
        expedientes: 2,
        importe_adjudicado: 260000,
        cuota_pct: 35.1,
        baja_mediana_pct: 12.5,
        bajas_n: 2,
        ultima_adjudicacion: "2025-06-10",
        es_incumbente: true,
      },
      {
        nombre: "DELTA SA",
        empresa_id: 202,
        expedientes: 1,
        importe_adjudicado: 120000,
        cuota_pct: 16.2,
        baja_mediana_pct: 20,
        bajas_n: 1,
        ultima_adjudicacion: "2024-06-10",
        es_incumbente: false,
      },
      {
        nombre: "GAMMA SA",
        empresa_id: null,
        expedientes: 1,
        importe_adjudicado: 72000,
        cuota_pct: 9.7,
        baja_mediana_pct: null,
        bajas_n: 0,
        ultima_adjudicacion: null,
        es_incumbente: false,
      },
    ],
    propia: { expedientes: 1, importe_adjudicado: 240000, cuota_pct: 32.4 },
    identidad_conocida: true,
    sin_datos: null,
  },
  puja: {
    nivel: "organo_cpv4",
    ventana_meses: 36,
    base: "mixta",
    baja_ganadora_mediana_pct: 12.5,
    bajas_n: 6,
    baja_oferta_minima_mediana_pct: 25,
    ofertas_minimas_n: 3,
  },
  calculado_en: "2026-10-01T12:00:00+00:00",
};

const SIN_DATOS: CompetenciaEsperada = {
  licitacion_id: ID,
  cpv4: "7226",
  ofertas: {
    ventana_meses: 24,
    sin_datos: "Ningún expediente adjudicado de este CPV publica cuántas ofertas recibió.",
  },
  incumbente: null,
  rivales: {
    ventana_meses: 36,
    expedientes: 0,
    importe_total: 0,
    muestra_suficiente: false,
    items: [],
    identidad_conocida: true,
    sin_datos: "Ninguna adjudicación del CPV 7226 en los últimos 36 meses.",
  },
  puja: null,
  calculado_en: "2026-10-01T12:00:00+00:00",
};

function responder(competencia: unknown, vigiladas: number[] = []) {
  fetchWithAuth.mockImplementation((url: string) => {
    if (url.includes("/competencia-esperada")) return Promise.resolve(competencia);
    if (url.includes("/competitive/watchlist")) {
      return Promise.resolve({ items: vigiladas.map((empresa_id) => ({ empresa_id })) });
    }
    return Promise.reject(new Error(`sin doble para ${url}`));
  });
}

function renderBloque() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      {/* El título lleva el `?` del glosario, que es un Tooltip. */}
      <TooltipProvider>
        <CompetenciaEsperadaBlock licitacionId={ID} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const urlsPedidas = () => fetchWithAuth.mock.calls.map((llamada) => String(llamada[0]));

beforeEach(() => {
  organizacion.id = 21;
});

afterEach(() => {
  cleanup();
  fetchWithAuth.mockReset();
});

describe("describirSegmento", () => {
  it.each([
    ["organo_cpv4", "este órgano en el CPV 7226"],
    ["cpv4_ccaa", "el CPV 7226 en Madrid"],
    ["cpv4", "el CPV 7226, todos los órganos"],
  ] as const)("%s", (nivel, texto) => {
    expect(describirSegmento(nivel, "7226", "Madrid")).toBe(texto);
  });
});

describe("CompetenciaEsperadaBlock", () => {
  it("pregunta por el expediente con la organización activa", async () => {
    responder(COMPLETA);
    renderBloque();
    await screen.findByText("~3");
    expect(urlsPedidas()[0]).toBe(
      "/api/v1/licitaciones/PA-S%202026%2F000058/competencia-esperada?organization_id=21",
    );
  });

  it("no pregunta antes de saber la organización", () => {
    organizacion.id = undefined;
    responder(COMPLETA);
    renderBloque();
    expect(fetchWithAuth).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: /Competencia esperada/ })).toBeInTheDocument();
  });

  it("sin organización elegida pregunta sin el parámetro: la resuelve la API", async () => {
    organizacion.id = null;
    responder(COMPLETA);
    renderBloque();
    await screen.findByText("~3");
    expect(urlsPedidas()[0]).toBe("/api/v1/licitaciones/PA-S%202026%2F000058/competencia-esperada");
  });

  it("dice cuántos se presentarán, con su universo, su ventana y su n", async () => {
    responder(COMPLETA);
    renderBloque();
    expect(await screen.findByText("~3")).toBeInTheDocument();
    expect(screen.getByText("ofertas esperadas")).toBeInTheDocument();
    expect(screen.getByText(/Media de 2,8 en este órgano en el CPV 7226; 17% con oferta única/)).toBeInTheDocument();
    const bandas = screen.getByRole("list", { name: "Reparto por número de ofertas" });
    expect(within(bandas).getByText("1 oferta · 17%")).toBeInTheDocument();
    expect(within(bandas).getByText("2–4 ofertas · 67%")).toBeInTheDocument();
    expect(within(bandas).getByText("5 o más · 17%")).toBeInTheDocument();
    expect(screen.getByText(/6 expedientes con el dato de 8 adjudicados · últimos 24 meses/)).toBeInTheDocument();
    // La media del CPV, la que explica la barra del score, sigue a la vista.
    expect(screen.getByText(/En todo el CPV 7226: 3,9 de media, la que usa la puntuación/)).toBeInTheDocument();
  });

  it("dice quién lo tiene hoy y lleva al contrato anterior y a su dossier", async () => {
    responder(COMPLETA);
    renderBloque();
    const enlace = await screen.findByRole("link", { name: "ALFA SA" });
    expect(enlace).toHaveAttribute("href", "/competencia/empresa/101");
    expect(screen.getByText(/Ganó el contrato anterior de este órgano con el mismo objeto/)).toHaveTextContent(
      /\(baja del 13,2%\)/,
    );
    expect(screen.getByRole("link", { name: /Ver el contrato anterior/ })).toHaveAttribute("href", "/detalle?lic=H0");
  });

  it("dice contra quién, con su cuota, marca al incumbente y a las vigiladas", async () => {
    responder(COMPLETA, [202]);
    renderBloque();
    const lista = await screen.findByRole("list", { name: "Rivales del segmento" });
    const filas = within(lista).getAllByRole("listitem");
    expect(filas).toHaveLength(3);
    expect(within(filas[0]).getByRole("link", { name: "ALFA CONSULTORÍA SA" })).toHaveAttribute(
      "href",
      "/competencia/empresa/101",
    );
    expect(within(filas[0]).getByText("2 exp. · 35%")).toBeInTheDocument();
    expect(within(filas[0]).getByText("Incumbente")).toBeInTheDocument();
    expect(within(filas[0]).getByText("Baja mediana 12,5%")).toBeInTheDocument();
    // Una sola baja no es una mediana.
    expect(within(filas[1]).getByText("Baja 20,0%")).toBeInTheDocument();
    expect(await within(filas[1]).findByText("Vigilada")).toBeInTheDocument();
    // Sin `empresa_id` no hay dossier al que llevar.
    expect(within(filas[2]).queryByRole("link")).not.toBeInTheDocument();
    expect(within(filas[2]).getByText("GAMMA SA")).toBeInTheDocument();

    expect(screen.getByText(/Tu organización: 32,4% del importe adjudicado/)).toBeInTheDocument();
    expect(
      screen.getByText(/Cuota sobre lo adjudicado en este órgano en el CPV 7226: últimos 36 meses, 6 expedientes/),
    ).toBeInTheDocument();
  });

  it("dice cómo se puja en el segmento", async () => {
    responder(COMPLETA);
    renderBloque();
    expect(await screen.findByText("Baja típica del ganador")).toBeInTheDocument();
    expect(screen.getByText("12,5%")).toBeInTheDocument();
    expect(screen.getByText("Baja de la oferta más baja")).toBeInTheDocument();
    expect(screen.getByText(/sobre 6 adjudicaciones \(3 publican la oferta más baja\)/)).toBeInTheDocument();
  });

  it("sin el NIF de tu organización avisa de que podría colarse entre los rivales", async () => {
    responder({ ...COMPLETA, rivales: { ...COMPLETA.rivales, propia: null, identidad_conocida: false } });
    renderBloque();
    expect(await screen.findByText(/Tu organización no ha declarado su NIF/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Declararlo en Equipo › Organización/ })).toHaveAttribute(
      "href",
      "/equipo",
    );
  });

  it("con la muestra corta lo dice", async () => {
    responder({ ...COMPLETA, rivales: { ...COMPLETA.rivales, muestra_suficiente: false } });
    renderBloque();
    expect(await screen.findByText(/Muestra corta: pocos expedientes en el segmento/)).toBeInTheDocument();
  });

  it("sin datos dice por qué en cada pregunta, sin ceros ni guiones", async () => {
    responder(SIN_DATOS);
    renderBloque();
    expect(
      await screen.findByText("Ningún expediente adjudicado de este CPV publica cuántas ofertas recibió."),
    ).toBeInTheDocument();
    expect(screen.getByText("No consta un contrato anterior de este órgano con el mismo objeto.")).toBeInTheDocument();
    expect(screen.getByText("Ninguna adjudicación del CPV 7226 en los últimos 36 meses.")).toBeInTheDocument();
    expect(screen.queryByText("Cómo se puja")).not.toBeInTheDocument();
    // Sin rivales no hace falta preguntar por las vigiladas.
    expect(urlsPedidas().some((url) => url.includes("/competitive/watchlist"))).toBe(false);
  });

  it("sin muestra en el CPV dice que la estimación es la media de todo el mercado", async () => {
    responder({
      ...COMPLETA,
      ofertas: {
        ventana_meses: 24,
        estimacion: 3,
        estimacion_nivel: "global",
        organo_cpv4: null,
        cpv4: null,
        media_global: 3.4,
      },
    });
    renderBloque();
    expect(await screen.findByText(/Media de todo el mercado: 3,4\./)).toHaveTextContent(
      "El CPV 7226 no tiene muestra propia en los últimos 24 meses.",
    );
  });

  it("un fallo se dice y se puede reintentar, no se lee como «sin rivales»", async () => {
    fetchWithAuth.mockRejectedValue(new ApiError(503, "Servicio no disponible", undefined, "GET /x"));
    renderBloque();
    expect(await screen.findByText("No se pudo calcular la competencia esperada")).toBeInTheDocument();
    expect(screen.queryByText(/Ninguna empresa gana/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Reintentar/ }));
    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(2));
  });
});
