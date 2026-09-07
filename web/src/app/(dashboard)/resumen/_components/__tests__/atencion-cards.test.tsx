import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const fetchWithAuth = vi.hoisted(() => vi.fn((_url: string) => new Promise(() => {})));
vi.mock("@/lib/api-client", () => ({ fetchWithAuth }));

/**
 * El ámbito vive en nuqs; aquí sólo interesa el valor ya resuelto. `useScopedHref`
 * usa la implementación real de `mergeFiltersIntoPath` sobre un ámbito fijo, que
 * es justo lo que se quiere verificar: que el enlace de la tarjeta arrastra los
 * chips activos en vez de descartarlos.
 */
const scope = vi.hoisted(() => ({
  params: {} as Record<string, string>,
  qs: "",
  estados: [] as string[],
  q: "",
  importeMin: null as number | null,
  soloAbiertas: false,
}));

vi.mock("@/lib/filters", async () => {
  const real = await vi.importActual<typeof import("@/lib/filters")>("@/lib/filters");
  return {
    ...real,
    useFilterParams: () => scope.params,
    useFilters: () => ({
      q: scope.q,
      estados: scope.estados,
      importeMin: scope.importeMin,
      soloAbiertas: scope.soloAbiertas,
      ccaas: [],
      tecnologias: [],
      rango: { desde: null, hasta: null },
    }),
    useScopedHref: () => (path: string) => real.mergeFiltersIntoPath(path, scope.qs),
  };
});

import { AtencionCards } from "@/app/(dashboard)/resumen/_components/atencion-cards";

const HOY = {
  calientes: 12,
  vencen_48h: 37,
  nuevas_24h: 8,
  total_activas: 42100,
  importe_p75: 250000,
};

function key(base: string[], url: string) {
  return [...base, url, { ...scope.params }];
}

function renderCards(hoy: Record<string, unknown> = HOY) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  qc.setQueryData(key(["analytics", "resumen", "hoy"], "/api/v1/analytics/resumen/hoy"), hoy);
  return render(
    <QueryClientProvider client={qc}>
      <AtencionCards />
    </QueryClientProvider>,
  );
}

function hrefDe(titulo: string): string {
  const link = screen.getByText(titulo).closest("a");
  return link?.getAttribute("href") ?? "";
}

describe("AtencionCards", () => {
  beforeEach(() => {
    cleanup();
    // `mockReset` y no `mockClear`: los tests que resuelven el desglose dejan
    // puesta su implementación, y la siguiente prueba la heredaría.
    fetchWithAuth.mockReset();
    fetchWithAuth.mockImplementation(() => new Promise(() => {}));
    scope.params = {};
    scope.qs = "";
    scope.estados = [];
    scope.q = "";
    scope.importeMin = null;
    scope.soloAbiertas = false;
  });

  it("pinta los tres contadores que exigen acción hoy", () => {
    renderCards();
    expect(screen.getByText("37")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
  });

  it("«Total activas» ya no vive aquí: bajó a la tira de contexto", () => {
    // No exige nada para hoy y ocupaba un cuarto de la banda urgente. Se
    // comprueba por el número para que el test falle si vuelve a colarse.
    renderCards();
    expect(screen.queryByText("42.100")).not.toBeInTheDocument();
    expect(screen.queryByText("Total activas")).not.toBeInTheDocument();
  });

  it("arrastra el ámbito activo a los tres destinos", () => {
    // El bug: la tarjeta contaba dentro del ámbito («4.210 activas en Madrid»)
    // y su enlace abría /detalle sin la CCAA — otro universo, mismo número.
    scope.qs = "?ccaa=Madrid&tecnologia=SAP";
    renderCards();
    for (const titulo of ["Ver la cola de cierre", "Grandes en plazo", "Nuevas 24h"]) {
      expect(hrefDe(titulo)).toContain("ccaa=Madrid");
      expect(hrefDe(titulo)).toContain("tecnologia=SAP");
    }
  });

  it("conserva el recorte propio de la tarjeta junto al ámbito", () => {
    scope.qs = "?ccaa=Madrid";
    renderCards();
    expect(hrefDe("Nuevas 24h")).toMatch(/fecha_desde=\d{4}-\d{2}-\d{2}/);
    expect(hrefDe("Nuevas 24h")).toContain("ccaa=Madrid");
  });

  it("la cola de cierre abre la ventana que cuenta, y lo declara", () => {
    // Era el destino roto del rediseño: contaba 37 y abría las 148.000 del
    // catálogo entero. `GET /licitaciones` ya acota por `fecha_limite`.
    renderCards();
    const href = hrefDe("Ver la cola de cierre");
    expect(href).toMatch(/cierre_desde=\d{4}-\d{2}-\d{2}/);
    expect(href).toMatch(/cierre_hasta=\d{4}-\d{2}-\d{2}/);
    expect(screen.getByText("/detalle · cierra en 48h")).toBeInTheDocument();
    expect(screen.queryByText(/≈ \/detalle · cierra en 48h/)).not.toBeInTheDocument();
  });

  it("«Grandes en plazo» corta por el P75 que publica el endpoint", () => {
    renderCards();
    expect(hrefDe("Grandes en plazo")).toContain("importe_min=250000");
    expect(hrefDe("Grandes en plazo")).toContain("solo_abiertas=true");
    expect(screen.getByText("/detalle abiertas · importe ≥ P75")).toBeInTheDocument();
  });

  it("sin P75 publicado, «Grandes en plazo» vuelve a declararse aproximada", () => {
    // Con ámbito activo el percentil se recalcula sobre el subconjunto filtrado
    // y no sale del endpoint: enlazar con el P75 global cortaría por un umbral
    // que no es el que produjo la cifra.
    renderCards({ ...HOY, importe_p75: null });
    expect(hrefDe("Grandes en plazo")).not.toContain("importe_min");
    expect(screen.getByText(/≈ \/detalle abiertas · sin el corte P75/)).toBeInTheDocument();
  });

  it("sin nada que vencer, la cola se resuelve en verde y no pide el desglose", () => {
    renderCards({ ...HOY, vencen_48h: 0 });
    expect(screen.getByText("Nada vence en las próximas 48 horas")).toBeInTheDocument();
    // La petición del desglose va con `enabled`: sin cola no se lanza.
    const pedidas = fetchWithAuth.mock.calls.map(([url]) => url);
    expect(pedidas.some((url) => url.includes("cierre_desde"))).toBe(false);
  });

  it("con cola, pide el desglose acotado a la ventana de cierre", () => {
    renderCards();
    const pedidas = fetchWithAuth.mock.calls.map(([url]) => url);
    const cola = pedidas.find((url) => url.includes("/api/v1/licitaciones"));
    expect(cola).toBeDefined();
    expect(cola).toMatch(/cierre_desde=\d{4}-\d{2}-\d{2}/);
    expect(cola).toMatch(/cierre_hasta=\d{4}-\d{2}-\d{2}/);
    // `vencen_48h` cuenta sin guardia de estado, así que la lista tampoco la
    // pone: con ella enseñaría menos filas de las que promete el número.
    expect(cola).not.toContain("solo_abiertas");
  });

  it("el desglose no aplica los filtros que el contador ignora", () => {
    // Si la lista aplicara el ámbito entero saldría más estrecha que su propio
    // encabezado: «37» sobre las cuatro filas que sobreviven al chip de estado.
    scope.params = { estado: "PUB", q: "sanidad", ccaa: "Madrid" };
    renderCards();
    const cola = fetchWithAuth.mock.calls
      .map(([url]) => url)
      .find((url) => url.includes("/api/v1/licitaciones"));
    expect(cola).toContain("ccaa=Madrid");
    expect(cola).not.toContain("estado=PUB");
    expect(cola).not.toContain("q=sanidad");
  });

  it("desglosa la cola en filas, ordenadas por lo que queda y no por lo que llegó", async () => {
    // El cambio de fondo del rediseño: la tarjeta pasa de decir «37» a decir
    // *cuáles*. El endpoint no ordena por `fecha_limite` —no está entre los
    // valores de `sort`—, así que si esto no ordenase en cliente la tarjeta
    // enseñaría cuatro cualesquiera de la ventana.
    // El medio minuto de holgura no es decorativo: las horas se redondean
    // **hacia abajo** a propósito (un plazo que se agota no regala tiempo), así
    // que un cierre a exactamente +9 h se lee «8 h» en cuanto pasa un
    // milisegundo entre montar el componente y calcular el plazo.
    const enHoras = (h: number) => new Date(Date.now() + h * 3_600_000 + 30_000).toISOString();
    fetchWithAuth.mockImplementation((url: string) =>
      url.includes("/api/v1/licitaciones")
        ? Promise.resolve({
            total: 2,
            items: [
              {
                id_externo: "LEJOS",
                titulo: "Cierra pasado mañana",
                organo_contratacion: "Universidad de Sevilla",
                importe: 740000,
                fecha_limite: enHoras(38),
              },
              {
                id_externo: "PRONTO",
                titulo: "Cierra esta tarde",
                organo_contratacion: "AEAT",
                importe: 4820000,
                fecha_limite: enHoras(9),
              },
            ],
          })
        : new Promise(() => {}),
    );

    renderCards();

    expect(await screen.findByText("Cierra esta tarde")).toBeInTheDocument();
    expect(screen.getAllByText(/^\d+ h$/).map((n) => n.textContent)).toEqual(["9 h", "38 h"]);
    // Cada fila abre su ficha: es lo que ahorra el viaje al listado.
    expect(hrefDe("Cierra esta tarde")).toContain("lic=PRONTO");
    expect(screen.getByText("AEAT")).toBeInTheDocument();
  });

  it("avisa cuando el ámbito lleva filtros que el endpoint ignora", () => {
    scope.estados = ["PUB"];
    scope.q = "sanidad";
    renderCards();
    expect(screen.getByText(/no aplican búsqueda y estado/)).toBeInTheDocument();
  });

  it("no avisa cuando el ámbito sólo lleva filtros que el endpoint sí aplica", () => {
    renderCards();
    expect(screen.queryByText(/no aplican/)).not.toBeInTheDocument();
  });
});
