import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * El bloque de fuentes pinta lo que la API declara, y nada más.
 *
 * Tres riesgos concretos, y los tres tienen precedente en este repo:
 *
 * 1. Que la página vuelva a llevar la lista escrita a mano. Por eso se
 *    comprueba con un inventario inventado por el test: si el componente
 *    pintara PLACSP por su cuenta, aparecería aquí sin que nadie lo mande.
 * 2. Que enseñe una tabla vacía cuando la API no respondió. El build de CI
 *    compila sin backend a propósito, y una lista de fuentes vacía en la
 *    página que declara el universo es peor que decir que falta.
 * 3. Que alguien añada un total. Sumar estos feeds daría un número con aspecto
 *    de cuota de mercado (`docs/regional-source-coverage.md`).
 */

vi.mock("../_lib/cobertura-api", () => ({ obtenerCobertura: vi.fn() }));

const { obtenerCobertura } = await import("../_lib/cobertura-api");
const { CoberturaDeclarada } = await import("../_components/cobertura-declarada");
type Cobertura = Awaited<ReturnType<typeof obtenerCobertura>>;

const COBERTURA = {
  fuentes: [
    {
      source_id: "fuente_viva",
      nombre: "Fuente viva",
      estado: "activa",
      alcance: "Universo declarado de la fuente viva.",
      max_lag_hours: 36,
    },
    {
      source_id: "fuente_apagable",
      nombre: "Fuente apagable",
      estado: "opcional",
      alcance: "Universo declarado de la fuente apagable.",
      max_lag_hours: 168,
    },
  ],
  fuera_de_alcance: [
    {
      ambito: "Ámbito excluido",
      motivo: "Motivo por el que no se ingiere.",
      decision: "D16",
      desde: "2026-09-06",
    },
  ],
  via_de_entrada: "Se abre un conector a petición escrita.",
} satisfies NonNullable<Cobertura>;

describe("CoberturaDeclarada", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("pinta cada fuente con su nombre, su estado, su alcance y su identificador", async () => {
    vi.mocked(obtenerCobertura).mockResolvedValue(COBERTURA);

    render(await CoberturaDeclarada());

    expect(screen.getByText("Fuente viva")).toBeInTheDocument();
    expect(screen.getByText("Universo declarado de la fuente viva.")).toBeInTheDocument();
    expect(screen.getByText("fuente_viva")).toBeInTheDocument();
    expect(screen.getByText("Fuente apagable")).toBeInTheDocument();
    // El estado sale del dato, no de una tabla local de la página. Aparece dos
    // veces —la etiqueta de la fila y la leyenda— y las dos son deliberadas.
    expect(screen.getAllByText("Activa").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Opcional").length).toBeGreaterThan(0);
  });

  it("no inventa fuentes que la API no declaró", async () => {
    vi.mocked(obtenerCobertura).mockResolvedValue(COBERTURA);

    const { container } = render(await CoberturaDeclarada());

    expect(container.textContent ?? "").not.toContain("PLACSP");
    expect(container.textContent ?? "").not.toContain("Euskadi");
  });

  it("no explica un estado que ninguna fuente usa", async () => {
    vi.mocked(obtenerCobertura).mockResolvedValue(COBERTURA);

    render(await CoberturaDeclarada());

    // "Fuera de alcance" es el título del bloque de exclusiones; lo que no debe
    // aparecer es su glosa como leyenda de un estado que nadie tiene.
    expect(screen.queryByText(/ni se ingiere ni se vigila/)).toBeNull();
  });

  it("declara lo que queda fuera con su decisión, su fecha y la vía de entrada", async () => {
    vi.mocked(obtenerCobertura).mockResolvedValue(COBERTURA);

    render(await CoberturaDeclarada());

    expect(screen.getByText("Ámbito excluido")).toBeInTheDocument();
    expect(screen.getByText("Motivo por el que no se ingiere.")).toBeInTheDocument();
    expect(screen.getByText("Se abre un conector a petición escrita.")).toBeInTheDocument();
    // La fecha va como `<time datetime>` legible por máquina; el formato
    // humano lo decide `formatDate` y afirmarlo aquí ataría el test al ICU.
    expect(document.querySelector('time[datetime="2026-09-06"]')).not.toBeNull();
  });

  it("dice que falta el inventario en vez de pintar una lista vacía", async () => {
    vi.mocked(obtenerCobertura).mockResolvedValue(null);

    render(await CoberturaDeclarada());

    expect(screen.getByText(/no se pudo leer/)).toBeInTheDocument();
    expect(screen.queryByRole("listitem")).toBeNull();
  });

  it("no pinta ningún porcentaje ni total agregado", async () => {
    vi.mocked(obtenerCobertura).mockResolvedValue(COBERTURA);

    const { container } = render(await CoberturaDeclarada());

    expect(container.textContent ?? "").not.toMatch(/\d+([.,]\d+)?\s*%/);
  });
});
