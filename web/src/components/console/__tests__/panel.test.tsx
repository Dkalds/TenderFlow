/**
 * Tests del vocabulario de panel de la consola (`components/console/panel.tsx`).
 *
 * Lo que se fija aquí no es el aspecto sino las reglas del sistema: los tres
 * estados ocupan el alto del contenido real para que la página no salte, la
 * tira de estadísticas es una rejilla y no cuatro tarjetas, y una celda sólo es
 * un botón cuando de verdad filtra algo.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import {
  Panel,
  PanelEmpty,
  PanelError,
  PanelLoading,
  PanelTabs,
  PanelTitle,
  SectionTitle,
  StatCell,
  StatStrip,
} from "@/components/console/panel";

afterEach(() => {
  cleanup();
});

describe("Panel", () => {
  it("pinta a sus hijos y respeta className y props del div", () => {
    render(
      <Panel className="mi-clase" data-testid="panel" aria-label="Panel de prueba">
        <span>contenido</span>
      </Panel>,
    );
    const panel = screen.getByTestId("panel");
    expect(panel).toHaveTextContent("contenido");
    expect(panel).toHaveClass("mi-clase");
    expect(panel).toHaveAttribute("aria-label", "Panel de prueba");
  });
});

describe("PanelTitle", () => {
  it("pinta el título como encabezado", () => {
    render(<PanelTitle title="Adjudicaciones por órgano" />);
    expect(screen.getByRole("heading", { name: "Adjudicaciones por órgano" })).toBeInTheDocument();
  });

  it("omite pista y acciones cuando no se pasan", () => {
    const { container } = render(<PanelTitle title="Sólo título" />);
    expect(container.querySelectorAll("span")).toHaveLength(0);
    expect(container.querySelector("button")).toBeNull();
  });

  it("muestra la pista de interacción junto al título", () => {
    // Un gráfico que filtra y no lo anuncia se explora a base de probar.
    render(<PanelTitle title="Órganos" hint="clic en una barra abre el órgano" />);
    expect(screen.getByText("clic en una barra abre el órgano")).toBeInTheDocument();
  });

  it("coloca las acciones cuando se pasan", () => {
    render(<PanelTitle title="Órganos" actions={<button type="button">Exportar</button>} />);
    expect(screen.getByRole("button", { name: "Exportar" })).toBeInTheDocument();
  });
});

describe("SectionTitle", () => {
  it("pinta el rótulo y su aside opcional", () => {
    render(<SectionTitle aside="12 filas">Resumen</SectionTitle>);
    expect(screen.getByRole("heading", { name: "Resumen" })).toBeInTheDocument();
    expect(screen.getByText("12 filas")).toBeInTheDocument();
  });

  it("sin aside no pinta el hueco", () => {
    render(<SectionTitle>Resumen</SectionTitle>);
    expect(screen.queryByText("12 filas")).not.toBeInTheDocument();
  });
});

describe("StatCell", () => {
  it("pinta etiqueta y valor", () => {
    render(<StatCell label="Importe total" value="1.234 €" />);
    expect(screen.getByText("Importe total")).toBeInTheDocument();
    expect(screen.getByText("1.234 €")).toBeInTheDocument();
  });

  it("mientras carga oculta el valor en vez de pintar un cero", () => {
    // Un cero mientras carga es un dato falso; el hueco es honesto.
    render(<StatCell label="Importe total" value="1.234 €" loading />);
    expect(screen.queryByText("1.234 €")).not.toBeInTheDocument();
    expect(screen.getByText("Importe total")).toBeInTheDocument();
  });

  it("marca la subida con signo y la bajada sin él", () => {
    const { rerender } = render(<StatCell label="Contratos" value="10" trend={4.25} />);
    expect(screen.getByText("+4.3%")).toBeInTheDocument();

    rerender(<StatCell label="Contratos" value="10" trend={-4.25} />);
    expect(screen.queryByText("+4.3%")).not.toBeInTheDocument();
    // El signo de la bajada lo pone `toFixed`, no el componente.
    expect(screen.getByText("-4.3%")).toBeInTheDocument();
  });

  it("trata el cero como subida y omite el delta si no hay tendencia", () => {
    const { rerender } = render(<StatCell label="Contratos" value="10" trend={0} />);
    expect(screen.getByText("+0.0%")).toBeInTheDocument();

    rerender(<StatCell label="Contratos" value="10" />);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("acepta badge, hint y color de acento", () => {
    render(
      <StatCell
        label="Importe resuelto"
        value="92%"
        badge={<span>revisar</span>}
        hint="por debajo del 95%"
        accent="rgb(255, 0, 0)"
      />,
    );
    expect(screen.getByText("revisar")).toBeInTheDocument();
    expect(screen.getByText("por debajo del 95%")).toBeInTheDocument();
    expect(screen.getByText("92%")).toHaveStyle({ color: "rgb(255, 0, 0)" });
  });

  it("sólo es botón cuando filtra: si no, es un div", () => {
    const onClick = vi.fn();
    const { rerender } = render(<StatCell label="CCAA" value="Madrid" onClick={onClick} />);
    const boton = screen.getByRole("button");
    fireEvent.click(boton);
    expect(onClick).toHaveBeenCalledTimes(1);

    rerender(<StatCell label="CCAA" value="Madrid" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("StatStrip", () => {
  it("expone el número de columnas como custom property", () => {
    const { container } = render(
      <StatStrip columns={6}>
        <StatCell label="a" value="1" />
      </StatStrip>,
    );
    expect(container.firstElementChild).toHaveStyle({ "--console-stat-columns": "6" });
  });

  it("usa cuatro columnas por defecto", () => {
    const { container } = render(
      <StatStrip>
        <StatCell label="a" value="1" />
      </StatStrip>,
    );
    expect(container.firstElementChild).toHaveStyle({ "--console-stat-columns": "4" });
  });
});

describe("PanelLoading", () => {
  it("reserva el alto del contenido real para que la página no salte", () => {
    const { container, rerender } = render(<PanelLoading />);
    expect(container.firstElementChild).toHaveStyle({ height: "260px" });

    rerender(<PanelLoading height={420} />);
    expect(container.firstElementChild).toHaveStyle({ height: "420px" });
  });
});

describe("PanelEmpty", () => {
  it("explica el vacío y admite una acción", () => {
    render(<PanelEmpty message="Sin datos en este ámbito" action={<button>Ampliar</button>} />);
    expect(screen.getByText("Sin datos en este ámbito")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ampliar" })).toBeInTheDocument();
  });

  it("aplica el alto mínimo sólo si se lo dan", () => {
    const { container, rerender } = render(<PanelEmpty message="Sin datos" height={300} />);
    expect(container.firstElementChild).toHaveStyle({ "min-height": "300px" });

    rerender(<PanelEmpty message="Sin datos" />);
    expect(container.firstElementChild?.getAttribute("style")).toBeFalsy();
  });
});

describe("PanelError", () => {
  it("se anuncia como alerta con su título por defecto", () => {
    render(<PanelError />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("No se pudo cargar")).toBeInTheDocument();
  });

  it("admite título y detalle propios", () => {
    render(<PanelError title="Timeout" detail="504 tras 30s" height={200} />);
    expect(screen.getByText("Timeout")).toBeInTheDocument();
    expect(screen.getByText("504 tras 30s")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveStyle({ "min-height": "200px" });
  });

  it("ofrece reintentar sólo si hay a qué reintentar", () => {
    const onRetry = vi.fn();
    const { rerender } = render(<PanelError onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: /reintentar/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);

    rerender(<PanelError />);
    expect(screen.queryByRole("button", { name: /reintentar/i })).not.toBeInTheDocument();
  });
});

describe("PanelTabs", () => {
  const tabs = [
    { key: "uno", label: "Uno" },
    { key: "dos", label: "Dos", badge: 12 },
  ];

  it("se anuncia como tablist con su etiqueta", () => {
    render(<PanelTabs tabs={tabs} value="uno" onChange={vi.fn()} label="Cortes del panel" />);
    expect(screen.getByRole("tablist", { name: "Cortes del panel" })).toBeInTheDocument();
  });

  it("marca la pestaña activa con aria-selected", () => {
    render(<PanelTabs tabs={tabs} value="dos" onChange={vi.fn()} label="Cortes" />);
    expect(screen.getByRole("tab", { name: /Uno/ })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: /Dos/ })).toHaveAttribute("aria-selected", "true");
  });

  it("pinta el badge sólo en la pestaña que lo trae", () => {
    render(<PanelTabs tabs={tabs} value="uno" onChange={vi.fn()} label="Cortes" />);
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("emite la clave del corte al pulsar", () => {
    const onChange = vi.fn();
    render(<PanelTabs tabs={tabs} value="uno" onChange={onChange} label="Cortes" />);
    fireEvent.click(screen.getByRole("tab", { name: /Dos/ }));
    expect(onChange).toHaveBeenCalledWith("dos");
  });

  it("un badge de 0 se pinta: es dato, no ausencia de dato", () => {
    render(
      <PanelTabs
        tabs={[{ key: "cola", label: "Cola", badge: 0 }]}
        value="cola"
        onChange={vi.fn()}
        label="Cortes"
      />,
    );
    expect(screen.getByText("0")).toBeInTheDocument();
  });
});
