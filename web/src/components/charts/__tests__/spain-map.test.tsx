import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
    onEachFeature?.(feature, {
      bindTooltip: () => {},
      on: () => {},
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
});
