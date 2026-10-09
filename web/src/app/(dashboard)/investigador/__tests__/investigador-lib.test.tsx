/**
 * Las piezas puras de la consola del Investigador: el resaltado, los ajustes
 * persistidos, el CSV, la detección de preguntas, lo entendido de la frase y
 * el plazo.
 *
 * Se fijan aquí porque son las que no se ven en un E2E: la configuración
 * guardada de una versión anterior tiene que seguir cargando, el CSV lo lee una
 * hoja de cálculo y no una persona, y que «licencias SAP» no despierte al
 * asistente es una decisión de coste que nadie nota hasta que deja de cumplirse.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TextoResaltado } from "../_lib/highlight";
import { DEFAULT_CONFIG, EJEMPLOS, loadConfig, saveConfig } from "../_lib/config-storage";
import { exportCSV } from "../_lib/export-csv";
import { chipsDeInterpretacion, enlaceDeAlerta } from "../_lib/interpretacion";
import { plazoDe } from "../_lib/plazo";
import { esPregunta } from "../_lib/pregunta";
import type { Interpretacion, SearchResult } from "../_lib/types";

// Se tipa con la firma real de `@/lib/export` para que `mock.calls` llegue
// tipado y el Blob no haya que reafirmarlo con un `as`.
const descargarBlob = vi.hoisted(() =>
  vi.fn<(nombre: string, blob: Blob, recurso: "investigador") => void>(),
);
vi.mock("@/lib/export", () => ({ descargarBlob }));

/** Un resultado completo: el contrato no tiene campos opcionales. */
export function resultado(extra: Partial<SearchResult> = {}): SearchResult {
  return {
    id_externo: "A-1",
    titulo: "Mantenimiento de licencias SAP",
    organo_contratacion: "Ayuntamiento de Sevilla",
    importe: 800000,
    descripcion: "Renovación de licencias.",
    url: null,
    fecha_publicacion: "2026-03-10",
    fecha_limite: null,
    ccaa: "Andalucía",
    estado: "PUB",
    tecnologia: "SAP",
    score: 1,
    coincide_en: ["anuncio"],
    terminos_ausentes: [],
    titulo_tramos: [],
    extracto: [],
    pasaje: null,
    ...extra,
  };
}

function interpretacion(extra: Partial<Interpretacion> = {}): Interpretacion {
  return {
    texto: "mantenimiento sap",
    terminos: ["mantenimiento", "sap"],
    ccaa: [],
    importe_min: null,
    importe_max: null,
    solo_abiertas: false,
    fecha_desde: null,
    fecha_hasta: null,
    orden: "relevancia",
    ...extra,
  };
}

describe("TextoResaltado", () => {
  it("marca los tramos que casan y deja el resto como texto", () => {
    render(
      <p>
        <TextoResaltado
          tramos={[
            { texto: "Mantenimiento de ", resaltado: false },
            { texto: "licencias", resaltado: true },
            { texto: " ", resaltado: false },
            { texto: "SAP", resaltado: true },
          ]}
        />
      </p>,
    );
    expect(screen.getByText("licencias").tagName).toBe("MARK");
    expect(screen.getByText("SAP").tagName).toBe("MARK");
    expect(screen.getByText(/Mantenimiento de/).tagName).toBe("P");
  });

  it("sin tramos enseña la alternativa", () => {
    render(
      <p>
        <TextoResaltado tramos={[]} alternativa="Título sin marcar" />
      </p>,
    );
    expect(screen.getByText("Título sin marcar")).toBeInTheDocument();
  });

  it("un texto de terceros con marcado no se interpreta", () => {
    // El extracto sale de un PDF: se pinta como texto, nunca como HTML.
    const { container } = render(
      <p>
        <TextoResaltado tramos={[{ texto: "<img src=x onerror=alert(1)>", resaltado: true }]} />
      </p>,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("<img src=x onerror=alert(1)>").tagName).toBe("MARK");
  });
});

describe("loadConfig", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("sin nada guardado devuelve los valores por defecto", () => {
    expect(loadConfig()).toEqual(DEFAULT_CONFIG);
  });

  it("completa con los valores por defecto las claves que el guardado no trae", () => {
    // Una configuración escrita antes de que existiera `alpha` no lo tiene; sin
    // el relleno, el deslizador de peso semántico arrancaría en `undefined`.
    window.localStorage.setItem("lsap:v1:investigador_config", JSON.stringify({ topK: 25 }));
    expect(loadConfig()).toEqual({ ...DEFAULT_CONFIG, topK: 25 });
  });

  it("lo guardado se vuelve a leer", () => {
    saveConfig({ ...DEFAULT_CONFIG, alpha: 0.25, model: "gpt-x" });
    expect(loadConfig().alpha).toBe(0.25);
    expect(loadConfig().model).toBe("gpt-x");
  });
});

describe("exportCSV", () => {
  beforeEach(() => {
    descargarBlob.mockClear();
  });

  async function csvEmitido(results: SearchResult[], source: string | null): Promise<string> {
    exportCSV(results, source);
    expect(descargarBlob).toHaveBeenCalledTimes(1);
    const [, blob] = descargarBlob.mock.calls[0];
    return await blob.text();
  }

  it("escribe la fuente de la respuesta en cada fila, no un campo por resultado", async () => {
    const csv = await csvEmitido([resultado({ titulo: "Obra" })], "fts");
    const [cabecera, fila] = csv.split("\n");
    expect(cabecera.split(",").at(-1)).toBe("source");
    expect(fila.split(",").at(-1)).toBe("fts");
  });

  it("dice dónde casa cada resultado, no un porcentaje", async () => {
    const csv = await csvEmitido([resultado({ coincide_en: ["anuncio", "pliego"] })], "fts");
    const [cabecera, fila] = csv.split("\n");
    expect(cabecera).toContain("coincide_en");
    expect(cabecera).not.toContain("score");
    expect(fila).toContain("anuncio+pliego");
  });

  it("escapa las comillas del título en vez de romper la columna", async () => {
    const csv = await csvEmitido([resultado({ titulo: 'Obra "grande"' })], null);
    expect(csv.split("\n")[1]).toContain('"Obra ""grande"""');
  });

  it("un id de expediente con comas no parte la fila", async () => {
    const csv = await csvEmitido([resultado({ id_externo: "7783/2025, ABI MIXTO" })], null);
    expect(csv.split("\n")[1].startsWith('"7783/2025, ABI MIXTO",')).toBe(true);
  });

  it("se emite por `descargarBlob`, que es lo que mide la descarga", async () => {
    await csvEmitido([resultado()], "fts");
    expect(descargarBlob.mock.calls[0][2]).toBe("investigador");
  });
});

describe("esPregunta", () => {
  it.each([
    "¿Qué es un PCAP y qué contiene?",
    "Que licitaciones han tenido bajada temeraria?",
    "Puedes mirar licitaciones relacionadas con licencia",
    "cuántas licitaciones de SAP hay en Madrid",
    "por qué se anulan los concursos",
    "Resumen de licitaciones de mantenimiento en Madrid",
    "dame las de Oracle",
  ])("%s → pregunta", (texto) => {
    expect(esPregunta(texto)).toBe(true);
  });

  it.each([
    "licencias SAP",
    "mantenimiento SAP abiertas en Andalucía",
    "baja temeraria",
    "últimas licitaciones de S/4HANA",
    "por lotes",
    "   ",
  ])("%s → búsqueda", (texto) => {
    // Unas palabras sueltas no despiertan al asistente: cuesta y tarda.
    expect(esPregunta(texto)).toBe(false);
  });

  it("los ejemplos de la pantalla enseñan los dos casos", () => {
    expect(EJEMPLOS.some(esPregunta)).toBe(true);
    expect(EJEMPLOS.some((e) => !esPregunta(e))).toBe(true);
  });
});

describe("chipsDeInterpretacion", () => {
  it("sin filtros entendidos no hay chips", () => {
    expect(chipsDeInterpretacion(interpretacion())).toEqual([]);
    expect(chipsDeInterpretacion(null)).toEqual([]);
  });

  it("pone cada filtro en palabras", () => {
    const chips = chipsDeInterpretacion(
      interpretacion({
        ccaa: ["Madrid", "Cataluña"],
        importe_min: 500000,
        solo_abiertas: true,
        fecha_desde: "2025-01-01",
        orden: "recientes",
      }),
    );
    expect(chips.slice(0, 2)).toEqual(["Madrid", "Cataluña"]);
    expect(chips[2]).toMatch(/^Más de 500\.000/);
    expect(chips[3]).toBe("Abiertas");
    expect(chips[4]).toMatch(/^Publicadas desde el 1 ene 2025$/);
    expect(chips[5]).toBe("Más recientes primero");
  });

  it("un rango de importe y un rango de fechas son un chip cada uno", () => {
    const chips = chipsDeInterpretacion(
      interpretacion({
        importe_min: 100000,
        importe_max: 500000,
        fecha_desde: "2025-01-01",
        fecha_hasta: "2025-12-31",
      }),
    );
    expect(chips).toHaveLength(2);
    expect(chips[0]).toMatch(/^Entre 100\.000.* y 500\.000/);
    expect(chips[1]).toMatch(/^Publicadas del 1 ene 2025 al 31 dic 2025$/);
  });
});

describe("enlaceDeAlerta", () => {
  function prefill(enlace: string): Record<string, string> {
    const url = new URL(enlace, "https://tenderflow.test");
    expect(url.pathname).toBe("/mi-watchlist");
    return JSON.parse(url.searchParams.get("prefill") ?? "{}") as Record<string, string>;
  }

  it("lleva la búsqueda con las claves que lee «Nueva regla»", () => {
    // Las mismas que manda la paleta: `q`, `ccaa`, `tecnologia`, `importe_min`
    // (`mi-watchlist/_hooks/use-watchlist-rules.ts::prefillToFormState`).
    expect(
      prefill(
        enlaceDeAlerta({
          texto: "mantenimiento sap",
          ccaa: ["Andalucía", "Madrid"],
          tecnologia: ["SAP"],
          importeMin: 500000,
        }),
      ),
    ).toEqual({ q: "mantenimiento sap", ccaa: "Andalucía,Madrid", tecnologia: "SAP", importe_min: "500000" });
  });

  it("lo que no hay no viaja", () => {
    expect(prefill(enlaceDeAlerta({ texto: " sap ", ccaa: [], tecnologia: [], importeMin: null }))).toEqual({
      q: "sap",
    });
  });
});

describe("plazoDe", () => {
  const ahora = new Date("2026-10-09T12:00:00");

  it("sin fecha, o con una que no se entiende, no dice nada", () => {
    expect(plazoDe(null, ahora)).toBeNull();
    expect(plazoDe("", ahora)).toBeNull();
    expect(plazoDe("pronto", ahora)).toBeNull();
  });

  it("un plazo futuro se dice como abierto", () => {
    expect(plazoDe("2026-11-12", ahora)).toEqual({ texto: "Plazo hasta el 12 nov 2026", vencido: false });
  });

  it("un plazo pasado se dice como cerrado", () => {
    expect(plazoDe("2026-03-03", ahora)).toEqual({ texto: "Plazo cerrado el 3 mar 2026", vencido: true });
  });

  it("el día del cierre sigue abierto hasta que acaba", () => {
    expect(plazoDe("2026-10-09", ahora)?.vencido).toBe(false);
  });
});
