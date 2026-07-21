import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { ForceGraph, type GraphNode, type GraphLink } from "../force-graph";

// jsdom no implementa matchMedia. Lo forzamos a reduced-motion para que el
// layout sea síncrono y determinista (sin timers de d3-force).
beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
      onchange: null,
    })),
  });
});

const NODES: GraphNode[] = [
  { id: "organo::A", label: "Órgano A", group: "organo", size: 100, column: 0 },
  { id: "empresa::X", label: "Empresa X", group: "empresa", size: 80, column: 1 },
  { id: "empresa::Y", label: "Empresa Y", group: "empresa", size: 40, column: 1 },
];
const LINKS: GraphLink[] = [
  { source: "organo::A", target: "empresa::X", weight: 5 },
  { source: "organo::A", target: "empresa::Y", weight: 2 },
];

function renderGraph(props: Partial<React.ComponentProps<typeof ForceGraph>> = {}) {
  return render(
    <ForceGraph
      nodes={NODES}
      links={LINKS}
      layout="bipartite"
      groupLabels={{ organo: "Órgano", empresa: "Empresa" }}
      {...props}
    />,
  );
}

describe("ForceGraph", () => {
  it("renderiza una leyenda dirigida por datos con un swatch por grupo", () => {
    const { container } = renderGraph();
    // Las etiquetas de la leyenda usan groupLabels.
    expect(screen.getByText("Órgano")).toBeInTheDocument();
    expect(screen.getByText("Empresa")).toBeInTheDocument();
    // Hay botón de re-encuadre.
    expect(screen.getByRole("button", { name: /Encuadrar/ })).toBeInTheDocument();
    // Un círculo por nodo.
    const circles = container.querySelectorAll('[data-testid="graph-nodes"] circle');
    expect(circles.length).toBe(NODES.length);
  });

  it("la leyenda y los nodos comparten exactamente el mismo color por grupo", () => {
    const { container } = renderGraph();
    // Color del círculo del grupo "organo" (atributo fill, hex de la escala d3).
    const organoCircle = container.querySelector('circle[data-group="organo"]');
    const fill = organoCircle?.getAttribute("fill");
    expect(fill).toBeTruthy();
    // El swatch de la leyenda "Órgano" debe tener ese mismo color.
    const swatch = screen.getByText("Órgano").querySelector("span");
    // jsdom normaliza el hex a rgb(); comparamos convirtiendo el hex del fill.
    const hexToRgb = (hex: string) => {
      const m = hex.replace("#", "");
      const r = parseInt(m.slice(0, 2), 16);
      const g = parseInt(m.slice(2, 4), 16);
      const b = parseInt(m.slice(4, 6), 16);
      return `rgb(${r}, ${g}, ${b})`;
    };
    expect(swatch?.style.backgroundColor).toBe(hexToRgb(fill!));
  });

  it("dispara onNodeClick con el id del nodo al hacer click", () => {
    const onNodeClick = vi.fn();
    const { container } = renderGraph({ onNodeClick });
    const circle = container.querySelector('circle[data-id="empresa::X"]');
    expect(circle).not.toBeNull();
    fireEvent.click(circle!);
    expect(onNodeClick).toHaveBeenCalledWith("empresa::X");
  });

  it("highlightIds atenúa los nodos no resaltados (resaltado revivido)", () => {
    const { container } = renderGraph({ highlightIds: ["empresa::X"] });
    const highlighted = container.querySelector('circle[data-id="empresa::X"]');
    const dimmed = container.querySelector('circle[data-id="empresa::Y"]');
    expect(highlighted?.getAttribute("opacity")).toBe("1");
    expect(dimmed?.getAttribute("opacity")).toBe("0.15");
  });

  it('layout="ego" fija el nodo central en el centro del lienzo', () => {
    // height por defecto 420 → centro virtual (VW/2, VH/2) = (500, 210).
    const { container } = renderGraph({ layout: "ego", centerId: "organo::A" });
    const center = container.querySelector('circle[data-id="organo::A"]');
    expect(center?.getAttribute("cx")).toBe("500");
    expect(center?.getAttribute("cy")).toBe("210");
    // Los vecinos no quedan en el centro (se reparten en el anillo).
    const neighbor = container.querySelector('circle[data-id="empresa::X"]');
    expect(neighbor?.getAttribute("cx")).not.toBe("500");
  });
});
