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

const HOY = { calientes: 12, vencen_48h: 37, nuevas_24h: 8, total_activas: 42100 };

function key(base: string[], url: string) {
  return [...base, url, { ...scope.params }];
}

function renderCards() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  qc.setQueryData(
    key(["analytics", "resumen", "hoy"], "/api/v1/analytics/resumen/hoy"),
    HOY,
  );
  qc.setQueryData(
    key(["analytics", "resumen", "novedades"], "/api/v1/analytics/resumen/novedades"),
    { count: 0, sample: [] },
  );
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

  it("marca con ≈ los destinos que el backend no sabe filtrar", () => {
    renderCards();
    // No hay filtro por fecha de cierre ni por el P75 de importe en
    // GET /licitaciones: el pie lo dice en vez de prometer un listado exacto.
    expect(screen.getByText(/≈ \/detalle · sin filtro de cierre/)).toBeInTheDocument();
    expect(screen.getByText(/≈ \/detalle abiertas · sin el corte P75/)).toBeInTheDocument();
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
