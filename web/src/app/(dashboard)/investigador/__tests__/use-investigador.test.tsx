/**
 * `useInvestigador` sin árbol de render: qué se pide, cuándo y con qué.
 *
 * La URL es la real (nuqs con su adaptador de pruebas) y la caché de React
 * Query también; se doblan la red, el hilo del asistente y el ámbito. Lo que
 * se fija aquí es lo que la pantalla no deja ver fácil:
 *
 * - la consulta vive en la URL y la petición entera entra en la clave de caché;
 * - una pregunta despierta al asistente y unas palabras sueltas no;
 * - el alcance del asistente viaja con cada pregunta;
 * - «Resultados» no se manda al asistente por encima de lo que admite.
 */

import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsTestingAdapter, type UrlUpdateEvent } from "nuqs/adapters/testing";
import type { SearchResult, SemanticSearchResponse } from "../_lib/types";

const fetchWithAuth = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", () => ({ fetchWithAuth }));

const registrarEvento = vi.hoisted(() => vi.fn());
vi.mock("@/lib/analytics", () => ({ registrarEvento }));

const ambito = vi.hoisted(() => ({
  ccaas: [] as string[],
  tecnologias: [] as string[],
  rango: { desde: null as string | null, hasta: null as string | null },
}));
vi.mock("@/lib/filters", () => ({ useFilters: () => ambito }));

const chat = vi.hoisted(() => ({
  send: vi.fn<(pregunta: string, opciones?: Record<string, unknown>) => Promise<void>>(async () => {}),
  reset: vi.fn(),
  stop: vi.fn(),
  messages: [] as { role: string; content: string }[],
  loading: false,
  streaming: false,
  error: null as Error | null,
}));
vi.mock("@/hooks/use-ask", () => ({
  useChat: () => chat,
  useAskModels: () => ({ data: ["modelo-a"] }),
}));

import { MAX_EXPEDIENTES_ASISTENTE, useInvestigador } from "../_hooks/use-investigador";

function hit(id: string, extra: Partial<SearchResult> = {}): SearchResult {
  return {
    id_externo: id,
    titulo: `Título ${id}`,
    organo_contratacion: "Órgano",
    importe: 1000,
    descripcion: null,
    url: null,
    fecha_publicacion: "2026-01-01",
    fecha_limite: null,
    ccaa: "Madrid",
    estado: "PUB",
    tecnologia: null,
    score: 1,
    coincide_en: ["anuncio"],
    terminos_ausentes: [],
    titulo_tramos: [],
    extracto: [],
    pasaje: null,
    ...extra,
  };
}

function respuesta(extra: Partial<SemanticSearchResponse> = {}): SemanticSearchResponse {
  return {
    q: "sap",
    top_k: 10,
    source: "fts",
    hits: [hit("A"), hit("B")],
    elapsed_ms: 12,
    interpretacion: {
      texto: "sap",
      terminos: ["sap"],
      ccaa: [],
      importe_min: null,
      importe_max: null,
      solo_abiertas: false,
      fecha_desde: null,
      fecha_hasta: null,
      orden: "relevancia",
    },
    ...extra,
  };
}

/** El cuerpo de la n-ésima petición de búsqueda. */
function cuerpo(n = -1): Record<string, unknown> {
  const llamada = fetchWithAuth.mock.calls.at(n);
  expect(llamada?.[0]).toBe("/api/v1/search/semantic");
  return JSON.parse((llamada?.[1] as { body: string }).body) as Record<string, unknown>;
}

function montar(searchParams = "") {
  const urls: UrlUpdateEvent[] = [];
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={cliente}>
      <NuqsTestingAdapter searchParams={searchParams} onUrlUpdate={(e) => urls.push(e)} hasMemory>
        {children}
      </NuqsTestingAdapter>
    </QueryClientProvider>
  );
  return { ...renderHook(() => useInvestigador(), { wrapper }), urls };
}

beforeEach(() => {
  window.localStorage.clear();
  fetchWithAuth.mockReset().mockResolvedValue(respuesta());
  registrarEvento.mockReset();
  chat.send.mockClear();
  chat.reset.mockClear();
  chat.messages = [];
  chat.loading = false;
  chat.error = null;
  ambito.ccaas = [];
  ambito.tecnologias = [];
  ambito.rango = { desde: null, hasta: null };
});

afterEach(cleanup);

describe("la consulta vive en la URL", () => {
  it("en blanco no pide nada y enseña el vacío", async () => {
    const { result } = montar();
    await waitFor(() => expect(result.current.models).toEqual(["modelo-a"]));

    expect(result.current.showEmpty).toBe(true);
    expect(result.current.searchResults).toBeNull();
    expect(fetchWithAuth).not.toHaveBeenCalled();
  });

  it("buscar la escribe en la URL, como una entrada del historial", async () => {
    const { result, urls } = montar();

    act(() => result.current.setTexto("  licencias sap  "));
    act(() => result.current.submit());

    await waitFor(() => expect(result.current.searchResults).toHaveLength(2));
    expect(urls.at(-1)?.searchParams.get("consulta")).toBe("licencias sap");
    expect(urls.at(-1)?.options.history).toBe("push");
    expect(result.current.consulta).toBe("licencias sap");
    expect(result.current.texto).toBe("licencias sap");
    expect(result.current.showEmpty).toBe(false);
  });

  it("con la consulta ya en la URL busca al montar, y rellena la caja", async () => {
    const { result } = montar("?consulta=baja+temeraria");

    expect(result.current.texto).toBe("baja temeraria");
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(cuerpo().q).toBe("baja temeraria");
    // Recargar o volver no despierta al asistente: no hay gesto que lo pida.
    expect(chat.send).not.toHaveBeenCalled();
  });

  it("la petición lleva lo que la búsqueda necesita", async () => {
    const { result } = montar();

    act(() => result.current.submit("licencias sap"));

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));
    expect(cuerpo()).toEqual({ q: "licencias sap", top_k: 10, alpha: 0.7, interpretar: true });
    expect(fetchWithAuth.mock.calls[0][1].method).toBe("POST");
  });

  it("repetir la misma consulta vuelve a pedirla", async () => {
    const { result } = montar("?consulta=sap");
    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));

    act(() => result.current.submit("sap"));

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(2));
  });

  it("el evento de búsqueda se emite al pedir, sin el término", async () => {
    fetchWithAuth.mockResolvedValue(respuesta({ hits: [] }));
    const { result } = montar();

    act(() => result.current.submit("algo que no existe"));

    await waitFor(() => expect(registrarEvento).toHaveBeenCalledTimes(1));
    expect(registrarEvento).toHaveBeenCalledWith("busqueda_realizada", {
      superficie: "investigador",
      con_resultados: "no",
    });
    expect(JSON.stringify(registrarEvento.mock.calls)).not.toContain("algo que no existe");
  });

  it("un fallo se enseña y se puede reintentar", async () => {
    fetchWithAuth.mockRejectedValueOnce(new Error("503"));
    const { result } = montar();

    act(() => result.current.submit("sap"));
    await waitFor(() => expect(result.current.error).toBeInstanceOf(Error));
    expect(result.current.searchResults).toBeNull();

    act(() => result.current.reintentar());
    await waitFor(() => expect(result.current.searchResults).toHaveLength(2));
    expect(result.current.error).toBeNull();
  });
});

describe("historial y ajustes", () => {
  it("cada consulta entra en «Recientes», sin repetirse, y sobrevive a la recarga", async () => {
    const { result } = montar();

    act(() => result.current.submit("uno"));
    act(() => result.current.submit("dos"));
    act(() => result.current.submit("uno"));

    expect(result.current.history).toEqual(["uno", "dos"]);
    cleanup();
    const otra = montar();
    await waitFor(() => expect(otra.result.current.history).toEqual(["uno", "dos"]));
  });

  it("«Resultados» cambia la petición", async () => {
    const { result } = montar("?consulta=sap");
    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));

    act(() => result.current.updateConfig({ topK: 25 }));

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(2));
    expect(cuerpo().top_k).toBe(25);
  });

  it("con ajustes guardados, una recarga pide una sola vez y con ellos", async () => {
    window.localStorage.setItem("lsap:v1:investigador_config", JSON.stringify({ topK: 30 }));

    montar("?consulta=sap");

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));
    expect(cuerpo().top_k).toBe(30);
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchWithAuth).toHaveBeenCalledTimes(1);
  });
});

describe("el ámbito", () => {
  beforeEach(() => {
    ambito.ccaas = ["Madrid", "Cataluña"];
    ambito.tecnologias = ["SAP"];
    ambito.rango = { desde: "2026-01-01", hasta: null };
  });

  it("apagado, no viaja ni se enseña", async () => {
    const { result } = montar("?consulta=sap");

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));
    expect(cuerpo()).not.toHaveProperty("ccaa");
    expect(result.current.activeSearchFilters).toEqual([]);
  });

  it("encendido, viajan todos los valores y se ven como chips", async () => {
    const { result } = montar("?consulta=sap");
    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));

    act(() => result.current.updateConfig({ useGlobalFilters: true }));

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(2));
    expect(cuerpo()).toMatchObject({
      ccaa: ["Madrid", "Cataluña"],
      tecnologia: ["SAP"],
      fecha_desde: "2026-01-01",
    });
    expect(cuerpo()).not.toHaveProperty("fecha_hasta");
    expect(result.current.activeSearchFilters).toEqual(["Madrid", "Cataluña", "SAP", "1 ene 2026 → …"]);
    expect(result.current.filtros.ccaa).toEqual(["Madrid", "Cataluña"]);
  });
});

describe("lo entendido de la frase", () => {
  it("llega de la respuesta", async () => {
    fetchWithAuth.mockResolvedValue(
      respuesta({ interpretacion: { ...respuesta().interpretacion, ccaa: ["Andalucía"] } }),
    );
    const { result } = montar("?consulta=sap+en+Andalucía");

    await waitFor(() => expect(result.current.interpretacion?.ccaa).toEqual(["Andalucía"]));
    expect(result.current.talCual).toBe(false);
  });

  it("«tal cual» vuelve a buscar sin interpretar, y queda en la URL", async () => {
    const { result, urls } = montar("?consulta=sap+en+Andalucía");
    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));

    act(() => result.current.setTalCual(true));

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(2));
    expect(cuerpo().interpretar).toBe(false);
    expect(urls.at(-1)?.searchParams.get("tal_cual")).toBe("1");
    expect(result.current.talCual).toBe(true);
  });

  it("una consulta nueva vuelve a leer la frase", async () => {
    const { result, urls } = montar("?consulta=sap&tal_cual=1");
    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));
    expect(cuerpo().interpretar).toBe(false);

    act(() => result.current.submit("oracle en Madrid"));

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(2));
    expect(cuerpo().interpretar).toBe(true);
    expect(urls.at(-1)?.searchParams.has("tal_cual")).toBe(false);
  });
});

describe("«Tipo de coincidencia»", () => {
  it("no se ofrece mientras ninguna respuesta combine significado y texto", async () => {
    const { result } = montar("?consulta=sap");

    await waitFor(() => expect(result.current.searchSource).toBe("fts"));
    expect(result.current.fusionDisponible).toBe(false);
  });

  it("aparece con la primera respuesta que sí combina, y se queda", async () => {
    fetchWithAuth.mockResolvedValueOnce(respuesta({ source: "rrf" }));
    const { result } = montar("?consulta=sap");
    await waitFor(() => expect(result.current.fusionDisponible).toBe(true));

    act(() => result.current.submit("oracle"));

    await waitFor(() => expect(result.current.searchSource).toBe("fts"));
    expect(result.current.fusionDisponible).toBe(true);
  });
});

describe("el asistente", () => {
  it("una pregunta se busca y además se responde, en una conversación nueva", async () => {
    const { result } = montar();

    act(() => result.current.submit("¿Qué es un PCAP?"));

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));
    expect(chat.reset).toHaveBeenCalledTimes(1);
    expect(chat.send).toHaveBeenCalledWith("¿Qué es un PCAP?", {
      model: undefined,
      topK: 10,
      extras: {},
      idsExternos: [],
    });
  });

  it("unas palabras sueltas solo se buscan", async () => {
    const { result } = montar();

    act(() => result.current.submit("licencias sap"));

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));
    expect(chat.send).not.toHaveBeenCalled();
  });

  it("«Resultados» no se manda al asistente por encima de lo que admite", async () => {
    const { result } = montar();
    act(() => result.current.updateConfig({ topK: 50, model: "modelo-a" }));

    act(() => result.current.preguntar("¿y el plazo?"));

    expect(chat.send).toHaveBeenCalledWith("¿y el plazo?", expect.objectContaining({ topK: 20, model: "modelo-a" }));
    // Una pregunta de seguimiento continúa la conversación.
    expect(chat.reset).not.toHaveBeenCalled();
  });

  it("el ámbito y «tal cual» viajan también al asistente", async () => {
    ambito.ccaas = ["Madrid"];
    const { result } = montar("?consulta=sap&tal_cual=1");
    act(() => result.current.updateConfig({ useGlobalFilters: true }));

    act(() => result.current.preguntar("¿cuál es la mayor?"));

    expect(chat.send.mock.calls.at(-1)?.[1]).toMatchObject({ extras: { ccaa: ["Madrid"], interpretar: false } });
  });

  it("una pregunta nueva desde la caja no hereda el «tal cual» de la consulta anterior", async () => {
    // Visto en el navegador: la lista de la consulta nueva se buscaba leyendo
    // los filtros de la frase y su respuesta, sin leerlos.
    const { result } = montar("?consulta=sap+en+Madrid&tal_cual=1");
    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));

    act(() => result.current.submit("¿Qué hay abierto en Galicia?"));

    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(2));
    expect(cuerpo().interpretar).toBe(true);
    expect(chat.send.mock.calls.at(-1)?.[1]).toMatchObject({ extras: {}, idsExternos: [] });
  });

  it("una pregunta vacía no se manda", () => {
    const { result } = montar();

    act(() => result.current.preguntar("   "));

    expect(chat.send).not.toHaveBeenCalled();
  });

  it("los resultados marcados son el alcance de la siguiente pregunta", async () => {
    const { result } = montar("?consulta=sap");
    await waitFor(() => expect(result.current.searchResults).toHaveLength(2));

    act(() => result.current.alternarSeleccion(hit("A")));
    act(() => result.current.alternarSeleccion(hit("B", { titulo: null })));
    expect(result.current.seleccion).toEqual([
      { id: "A", titulo: "Título A" },
      { id: "B", titulo: "B" },
    ]);

    act(() => result.current.preguntar("compara los plazos", { nueva: true }));

    expect(chat.reset).toHaveBeenCalledTimes(1);
    expect(chat.send.mock.calls.at(-1)?.[1]).toMatchObject({ idsExternos: ["A", "B"] });
  });

  it("marcar dos veces desmarca, y no caben más de tres", () => {
    const { result } = montar();

    act(() => result.current.alternarSeleccion(hit("A")));
    act(() => result.current.alternarSeleccion(hit("A")));
    expect(result.current.seleccion).toEqual([]);

    for (const id of ["A", "B", "C", "D"]) act(() => result.current.alternarSeleccion(hit(id)));
    expect(result.current.seleccion.map((s) => s.id)).toEqual(["A", "B", "C"]);
    expect(result.current.seleccion).toHaveLength(MAX_EXPEDIENTES_ASISTENTE);
    expect(result.current.seleccionLlena).toBe(true);

    act(() => result.current.quitarSeleccion("B"));
    expect(result.current.seleccion.map((s) => s.id)).toEqual(["A", "C"]);
    expect(result.current.seleccionLlena).toBe(false);
  });

  it("una consulta nueva suelta lo marcado: era de la lista anterior", async () => {
    const { result } = montar("?consulta=sap");
    await waitFor(() => expect(result.current.searchResults).toHaveLength(2));
    act(() => result.current.alternarSeleccion(hit("A")));

    act(() => result.current.submit("oracle"));

    expect(result.current.seleccion).toEqual([]);
  });

  it("con una conversación en marcha la pantalla no está vacía", () => {
    chat.messages = [{ role: "user", content: "hola" }];

    const { result } = montar();

    expect(result.current.showEmpty).toBe(false);
  });
});
