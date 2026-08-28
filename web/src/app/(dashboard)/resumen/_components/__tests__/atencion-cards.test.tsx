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
  qc.setQueryData(key(["analytics", "resumen", "novedades"], "/api/v1/analytics/resumen/novedades"), {
    count: 0,
    sample: [],
  });
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
    fetchWithAuth.mockClear();
    scope.params = {};
    scope.qs = "";
    scope.estados = [];
    scope.q = "";
    scope.importeMin = null;
    scope.soloAbiertas = false;
  });

  it("pinta los cuatro contadores de /resumen/hoy", () => {
    renderCards();
    expect(screen.getByText("37")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    // es-ES no agrupa a partir del cuarto dígito, sino del quinto: 4210 se
    // escribe «4210» y 42100, «42.100».
    expect(screen.getByText("42.100")).toBeInTheDocument();
  });

  it("arrastra el ámbito activo a los cuatro destinos", () => {
    // El bug: la tarjeta contaba dentro del ámbito («4.210 activas en Madrid»)
    // y su enlace abría /detalle sin la CCAA — otro universo, mismo número.
    scope.qs = "?ccaa=Madrid&tecnologia=SAP";
    renderCards();
    for (const titulo of ["Vencen 48h", "Grandes en plazo", "Nuevas 24h", "Total activas"]) {
      expect(hrefDe(titulo)).toContain("ccaa=Madrid");
      expect(hrefDe(titulo)).toContain("tecnologia=SAP");
    }
  });

  it("conserva el recorte propio de la tarjeta junto al ámbito", () => {
    scope.qs = "?ccaa=Madrid";
    renderCards();
    expect(hrefDe("Total activas")).toContain("solo_abiertas=true");
    expect(hrefDe("Nuevas 24h")).toMatch(/fecha_desde=\d{4}-\d{2}-\d{2}/);
  });

  it("«Vencen 48h» abre la ventana de cierre que cuenta", () => {
    // Era el destino roto del rediseño: contaba 37 y abría las 148.000 del
    // catálogo entero. `GET /licitaciones` ya acota por `fecha_limite`.
    renderCards();
    const href = hrefDe("Vencen 48h");
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

  it("«Total activas» sigue abriendo sólo las abiertas, sin ≈", () => {
    renderCards();
    expect(screen.getByText("/detalle sólo abiertas")).toBeInTheDocument();
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
