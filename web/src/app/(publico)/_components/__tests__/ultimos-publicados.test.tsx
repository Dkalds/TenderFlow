import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * El hero de la portada dejó de enseñar una captura para enseñar expedientes
 * reales, y eso mueve el riesgo de sitio: ya no es «la imagen está anticuada»,
 * es «la portada afirma algo sobre el dato». Lo que fijan estos tests:
 *
 * - que se pinta lo que devuelve el endpoint, sin ordenarlo ni recortarlo aquí
 *   (ADR-014: el orden lo pone el backend, y por eso el rótulo dice
 *   «publicados» y no «incorporados»);
 * - que cada fila enlaza a su ficha pública, que es lo que reparte autoridad
 *   interna hacia la superficie indexable;
 * - que sin anuncios no se pinta un hueco ni una lista vacía. El build de CI se
 *   hace sin backend, y una sección fantasma en portada es peor que ninguna.
 */
vi.mock("@/lib/publico-api", () => ({
  listarLicitaciones: vi.fn(),
}));

const { listarLicitaciones } = await import("@/lib/publico-api");
const { UltimosPublicados } = await import("../ultimos-publicados");

type Licitacion = Awaited<ReturnType<typeof listarLicitaciones>>["items"][number];

function anuncio(overrides: Partial<Licitacion> = {}): Licitacion {
  return {
    ref: "REF-1",
    titulo: "Servicios de mantenimiento SAP",
    organo_contratacion: "Junta de Andalucía",
    importe: 1200000,
    ccaa: "Andalucía",
    estado: "PUB",
    fecha_publicacion: "2026-09-01",
    fecha_limite: "2026-12-31",
    ...overrides,
  } as Licitacion;
}

function conAnuncios(items: Licitacion[]) {
  vi.mocked(listarLicitaciones).mockResolvedValue({ items, total: items.length });
}

describe("UltimosPublicados", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // El camino sin datos avisa por consola a propósito; sin esto el ruido
    // ensucia la salida del test que lo ejercita.
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  it("pinta los anuncios que devuelve la API, con su órgano e importe", async () => {
    conAnuncios([anuncio(), anuncio({ ref: "REF-2", titulo: "Licencias Microsoft 365" })]);

    render(await UltimosPublicados());

    expect(screen.getByText("Servicios de mantenimiento SAP")).toBeInTheDocument();
    expect(screen.getByText("Licencias Microsoft 365")).toBeInTheDocument();
    expect(screen.getAllByText("Junta de Andalucía")).toHaveLength(2);
  });

  it("enlaza cada anuncio a su ficha pública", async () => {
    conAnuncios([anuncio()]);

    render(await UltimosPublicados());

    const enlace = screen.getByRole("link", { name: /Servicios de mantenimiento SAP/ });
    expect(enlace).toHaveAttribute("href", "/licitaciones/andalucia/servicios-de-mantenimiento-sap/REF-1");
  });

  it("respeta el orden en que llegan: aquí no se ordena nada", async () => {
    // El endpoint ordena por fecha de publicación descendente
    // (`db/repositories/publico.py`). Reordenar en el cliente sería derivar un
    // criterio que el backend no dio.
    conAnuncios([
      anuncio({ ref: "A", titulo: "Primero", fecha_publicacion: "2026-08-01" }),
      anuncio({ ref: "B", titulo: "Segundo", fecha_publicacion: "2026-09-01" }),
    ]);

    render(await UltimosPublicados());

    const titulos = screen.getAllByRole("link").map((a) => a.textContent);
    expect(titulos[0]).toContain("Primero");
    expect(titulos[1]).toContain("Segundo");
  });

  it("no pinta nada cuando la API no devuelve anuncios", async () => {
    conAnuncios([]);

    expect(await UltimosPublicados()).toBeNull();
  });

  it("pide exactamente cinco y no filtra el resultado", async () => {
    conAnuncios([anuncio()]);

    await UltimosPublicados();

    expect(listarLicitaciones).toHaveBeenCalledWith({ limit: 5 });
  });

  it("no inventa la fecha del más reciente si el anuncio no la trae", async () => {
    conAnuncios([anuncio({ fecha_publicacion: null })]);

    render(await UltimosPublicados());

    expect(screen.queryByText(/El más reciente/)).not.toBeInTheDocument();
  });

  it("marca como cerrado el plazo vencido, en vez de anunciarlo como abierto", async () => {
    // Un plazo vencido presentado como «Hasta el …» es el peor error posible en
    // la superficie de adquisición: quien llega desde Google viene a presentarse.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2027-01-15T10:00:00Z"));
    conAnuncios([anuncio({ fecha_limite: "2026-12-31" })]);

    render(await UltimosPublicados());

    expect(screen.getByText(/Cerrado el/)).toBeInTheDocument();
    vi.useRealTimers();
  });
});
