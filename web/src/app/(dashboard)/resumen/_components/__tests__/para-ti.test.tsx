import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { RadarTender } from "@/hooks/use-radar";

/**
 * «Para ti» es la bandeja del Radar recortada: mismo ranking, mismo orden, y
 * fuera lo que ya sigues. No reordena ni tría: eso es del Radar.
 */

const radarState: {
  data?: { items: RadarTender[]; signals: null };
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
} = { data: undefined, isLoading: false, error: null, refetch: vi.fn() };
const seguidas = { ids: new Set<string>() };
const tecnologia = vi.fn();

vi.mock("@/hooks/use-radar", () => ({
  useRadar: (valor: string | null) => {
    tecnologia(valor);
    return radarState;
  },
}));
vi.mock("@/hooks/use-seguimiento", () => ({ useSeguimiento: () => seguidas }));
vi.mock("@/lib/filters", () => ({ useFilters: () => ({ tecnologias: ["SAP", "Salesforce"] }) }));
vi.mock("@/components/ficha/enlace-ficha", () => ({
  EnlaceFicha: ({ idExterno, children }: { idExterno: string; children: React.ReactNode }) => (
    <a href={`/detalle?lic=${idExterno}`}>{children}</a>
  ),
}));

import { ParaTi, VISIBLES_PARA_TI } from "../para-ti";

function senal(id: string, score: number, band = "Caliente"): RadarTender {
  return {
    id_externo: id,
    titulo: `Licencias ${id}`,
    score,
    band,
    organo_contratacion: "EJIE",
    ccaa: "País Vasco",
    importe: 2_900_000,
    tecnologia: "SAP",
  } as RadarTender;
}

beforeEach(() => {
  seguidas.ids = new Set();
  radarState.error = null;
  radarState.isLoading = false;
  radarState.data = {
    items: [senal("A", 77), senal("B", 76), senal("C", 75), senal("D", 69, "Atractiva"), senal("E", 64), senal("F", 60), senal("G", 55)],
    signals: null,
  };
});

describe("ParaTi", () => {
  it("pinta las primeras de la bandeja en el orden del backend, con la tecnología del ámbito", () => {
    render(<ParaTi />);
    const filas = within(screen.getByRole("list")).getAllByRole("link");
    expect(filas).toHaveLength(VISIBLES_PARA_TI);
    expect(filas.map((fila) => fila.getAttribute("href"))).toEqual(
      ["A", "B", "C", "D", "E"].map((id) => `/detalle?lic=${id}`),
    );
    expect(tecnologia).toHaveBeenLastCalledWith("SAP");
    expect(screen.getByText("7 por revisar en tu bandeja · por score")).toBeInTheDocument();
  });

  it("deja fuera lo que ya sigues, como la bandeja del Radar", () => {
    seguidas.ids = new Set(["A"]);
    render(<ParaTi />);
    expect(screen.queryByText("Licencias A")).toBeNull();
    expect(screen.getByText("6 por revisar en tu bandeja · por score")).toBeInTheDocument();
  });

  it("con la bandeja vacía lo dice y no pinta filas", () => {
    radarState.data = { items: [], signals: null };
    render(<ParaTi />);
    expect(screen.getByText("Nada por revisar en tu bandeja")).toBeInTheDocument();
    expect(screen.queryByRole("list")).toBeNull();
  });
});
