import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";

const fetchWithAuth = vi.hoisted(() => vi.fn((_url: string) => new Promise(() => {})));
vi.mock("@/lib/api-client", () => ({ fetchWithAuth }));

// El ámbito global vive en nuqs; aquí sólo interesa el valor ya resuelto que
// el feed manda a la API. `lib/filters` tiene su propio test.
const scope = vi.hoisted(() => ({
  params: {} as Record<string, string>,
  rango: { desde: null as string | null, hasta: null as string | null },
}));
vi.mock("@/lib/filters", () => ({
  useFilterParams: () => scope.params,
  useFilters: () => ({ rango: scope.rango }),
}));

import { EventosFeed } from "@/app/(dashboard)/resumen/_components/eventos-feed";

/** Misma clave que compone `useFilteredQuery`: baseKey + url + params. */
function feedKey() {
  return ["eventos", "feed", "/api/v1/eventos", { dias: "30", limit: "20", ...scope.params }];
}

function renderFeed(data?: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  if (data !== undefined) qc.setQueryData(feedKey(), data);
  // `TooltipProvider` porque `ImporteDelta` envuelve su cifra en un `<Tooltip>`
  // desde C7.4 (antes era un `title=` nativo, que no existe para el táctil). En
  // uso real el provider lo pone `components/providers.tsx`; aquí el componente
  // se monta suelto.
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <EventosFeed />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("EventosFeed", () => {
  beforeEach(() => {
    fetchWithAuth.mockClear();
    scope.params = {};
    scope.rango = { desde: null, hasta: null };
  });

  it("shows an empty state when there are no events", () => {
    renderFeed({ items: [], dias: 30 });
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders events with their type label and links to the detail page", () => {
    renderFeed({
      items: [
        {
          licitacion_id: "L1",
          tipo: "prorroga",
          fecha: "2026-07-01",
          detalle: null,
          importe_delta: null,
          titulo: "Mantenimiento SAP",
          organo_contratacion: "Ministerio X",
          fuente: "placsp",
        },
      ],
      dias: 30,
    });
    expect(screen.getByText("Prórroga")).toBeInTheDocument();
    const link = screen.getByText("Mantenimiento SAP").closest("a");
    expect(link).toHaveAttribute("href", "/detalle?lic=L1");
  });

  it("shows importe_delta with a sign and color", () => {
    renderFeed({
      items: [
        {
          licitacion_id: "L2",
          tipo: "modificacion",
          fecha: "2026-07-05",
          detalle: null,
          importe_delta: 5000,
          titulo: "Ampliación de suministro",
          organo_contratacion: null,
          fuente: "placsp",
        },
      ],
      dias: 30,
    });
    expect(screen.getByText(/\+/)).toBeInTheDocument();
  });

  it("falls back to the raw tipo when it is unknown", () => {
    renderFeed({
      items: [
        {
          licitacion_id: "L3",
          tipo: "algo_nuevo",
          fecha: null,
          detalle: null,
          importe_delta: null,
          titulo: null,
          organo_contratacion: null,
          fuente: null,
        },
      ],
      dias: 30,
    });
    expect(screen.getByText("algo_nuevo")).toBeInTheDocument();
  });

  it("draws the window's breakdown by type and counts the whole window", () => {
    const evento = (i: number, tipo: string) => ({
      licitacion_id: `L${i}`,
      tipo,
      fecha: "2026-07-01",
      detalle: null,
      importe_delta: null,
      titulo: `Contrato ${i}`,
      organo_contratacion: null,
      fuente: "placsp",
    });
    const { container } = renderFeed({
      items: Array.from({ length: 20 }, (_, i) => evento(i, i % 3 ? "adjudicacion" : "prorroga")),
      dias: 30,
      por_tipo: [
        { tipo: "adjudicacion", n: 98 },
        { tipo: "prorroga", n: 45 },
      ],
      total: 143,
    });
    const leyenda = screen.getByRole("list", { name: "Movimientos por tipo" });
    expect(leyenda).toHaveTextContent("Adjudicación98");
    expect(leyenda).toHaveTextContent("Prórroga45");
    // La barra reparte la ventana entera, tramo tras tramo.
    const tramos = container.querySelectorAll("svg[viewBox='0 0 143 1'] rect");
    expect(Array.from(tramos, (r) => [r.getAttribute("x"), r.getAttribute("width")])).toEqual([
      ["0", "98"],
      ["98", "45"],
    ]);
    // El pie cuenta la ventana, no las 20 filas pedidas.
    expect(screen.getByText("8 de 143")).toBeInTheDocument();
  });

  it("falls back to the sample size without a backend breakdown", () => {
    const items = Array.from({ length: 10 }, (_, i) => ({
      licitacion_id: `L${i}`,
      tipo: "prorroga",
      fecha: "2026-07-01",
      detalle: null,
      importe_delta: null,
      titulo: `Contrato ${i}`,
      organo_contratacion: null,
      fuente: "placsp",
    }));
    renderFeed({ items, dias: 30 });
    expect(screen.queryByRole("list", { name: "Movimientos por tipo" })).not.toBeInTheDocument();
    expect(screen.getByText("8 de 10")).toBeInTheDocument();
  });

  it("sends the active scope to the API", () => {
    scope.params = { ccaa: "Madrid", tecnologia: "SAP", fecha_desde: "2026-01-01" };
    renderFeed();
    const url = fetchWithAuth.mock.calls[0][0];
    expect(url).toContain("/api/v1/eventos?");
    expect(url).toContain("ccaa=Madrid");
    expect(url).toContain("tecnologia=SAP");
    expect(url).toContain("fecha_desde=2026-01-01");
    expect(url).toContain("dias=30");
  });

  it("describes the window taken from the scope dates", () => {
    scope.params = { fecha_desde: "2026-01-01", fecha_hasta: "2026-03-31" };
    scope.rango = { desde: "2026-01-01", hasta: "2026-03-31" };
    renderFeed({ items: [], dias: 30 });
    expect(screen.getByText(/Del .* al /)).toBeInTheDocument();
  });
});
