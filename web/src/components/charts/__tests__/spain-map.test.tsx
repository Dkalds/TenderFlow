import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SpainMap } from "@/components/charts/spain-map";

// react-leaflet cannot initialise a real Leaflet map in jsdom. Mock the pieces
// SpainMap uses and, for GeoJSON, invoke the `style` and `onEachFeature`
// callbacks so the color-scale and label helpers are actually exercised.
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="map-container">{children}</div>
  ),
  ZoomControl: () => null,
  GeoJSON: ({
    style,
    onEachFeature,
  }: {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    style?: (f: any) => unknown;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    onEachFeature?: (f: any, layer: any) => void;
  }) => {
    const feature = {
      type: "Feature",
      properties: { name: "Madrid" },
      geometry: { type: "Polygon", coordinates: [] },
    };
    style?.(feature);
    // El trazo de la región: Leaflet lo crea al añadir la capa y lo entrega
    // con `getElement()`. Aquí es un `<path>` real colgado del documento para
    // poder afirmar sus atributos y mandarle teclas.
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("data-testid", "region-madrid");
    document.body.appendChild(path);
    onEachFeature?.(feature, {
      bindTooltip: () => {},
      getElement: () => path,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      on: (handlers: Record<string, (...a: any[]) => void>) => handlers.add?.(),
    });
    return <div data-testid="geojson" />;
  },
}));

const GEOJSON = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", properties: { name: "Madrid" }, geometry: { type: "Polygon", coordinates: [] } },
  ],
};

const DATA = [
  { ccaa: "Comunidad de Madrid", value: 1_500_000_000 },
  { ccaa: "Cataluña", value: 2_000_000 },
  { ccaa: "Galicia", value: 3_500 },
];

describe("SpainMap", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows a loading state before the geojson resolves", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<SpainMap data={DATA} />);
    expect(screen.getByText("Cargando mapa…")).toBeInTheDocument();
  });

  it("shows an error state when the geojson fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("network"))));
    render(<SpainMap data={DATA} />);
    expect(await screen.findByText("Error cargando mapa")).toBeInTheDocument();
  });

  it("shows an error state on a non-ok response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: false, status: 404 } as Response)),
    );
    render(<SpainMap data={DATA} />);
    expect(await screen.findByText("Error cargando mapa")).toBeInTheDocument();
  });

  it("renders the map once the geojson resolves, exercising the color/label helpers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({ ok: true, json: () => Promise.resolve(GEOJSON) } as unknown as Response),
      ),
    );
    render(<SpainMap data={DATA} colorScale="green" metric="Importe" />);
    await waitFor(() => expect(screen.getByTestId("map-container")).toBeInTheDocument());
    expect(screen.getByTestId("geojson")).toBeInTheDocument();
  });

  it("cuando filtra, cada región es un botón con nombre que responde al teclado", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({ ok: true, json: () => Promise.resolve(GEOJSON) } as unknown as Response),
      ),
    );
    const onCcaaClick = vi.fn();
    render(<SpainMap data={DATA} metric="Licitaciones" onCcaaClick={onCcaaClick} />);
    expect(
      await screen.findByRole("region", { name: "Mapa de España por comunidad autónoma: Licitaciones" }),
    ).toHaveAccessibleDescription(/Tabulador/);

    const region = screen.getAllByTestId("region-madrid").at(-1)!;
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region).toHaveAttribute("role", "button");
    expect(region.getAttribute("aria-label")).toMatch(/^Madrid: Licitaciones .*Filtrar por esta comunidad$/);
    fireEvent.keyDown(region, { key: "Enter" });
    expect(onCcaaClick).toHaveBeenCalledWith("Madrid");
  });

  it("sin acción de filtrar, las regiones no se vuelven botones", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({ ok: true, json: () => Promise.resolve(GEOJSON) } as unknown as Response),
      ),
    );
    render(<SpainMap data={DATA} />);
    await waitFor(() => expect(screen.getByTestId("map-container")).toBeInTheDocument());
    expect(screen.getAllByTestId("region-madrid").at(-1)).not.toHaveAttribute("tabindex");
  });
});
