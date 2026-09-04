import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "@/components/ui/status-badge";

describe("StatusBadge — null / undefined value", () => {
  it("renders a dash for null value", () => {
    const { container } = render(<StatusBadge value={null} />);
    expect(container.textContent).toBe("-");
  });

  it("renders a dash for undefined value", () => {
    const { container } = render(<StatusBadge value={undefined} />);
    expect(container.textContent).toBe("-");
  });

  it("renders a dash for empty string", () => {
    const { container } = render(<StatusBadge value="" />);
    expect(container.textContent).toBe("-");
  });
});

describe("StatusBadge — estado kind (default)", () => {
  it("renders Publicada estado with its label", () => {
    render(<StatusBadge value="Publicada" />);
    expect(screen.getByText("Publicada")).toBeInTheDocument();
  });

  it("renders Adjudicada estado", () => {
    render(<StatusBadge value="Adjudicada" />);
    expect(screen.getByText("Adjudicada")).toBeInTheDocument();
  });

  it("renders Resuelta estado", () => {
    render(<StatusBadge value="Resuelta" />);
    expect(screen.getByText("Resuelta")).toBeInTheDocument();
  });

  it("renders Desierta estado", () => {
    render(<StatusBadge value="Desierta" />);
    expect(screen.getByText("Desierta")).toBeInTheDocument();
  });

  it("renders Anulada estado", () => {
    render(<StatusBadge value="Anulada" />);
    expect(screen.getByText("Anulada")).toBeInTheDocument();
  });

  it("renders En plazo estado", () => {
    render(<StatusBadge value="En plazo" />);
    expect(screen.getByText("En plazo")).toBeInTheDocument();
  });

  it("renders an unknown estado with neutral style", () => {
    render(<StatusBadge value="Desconocida" />);
    expect(screen.getByText("Desconocida")).toBeInTheDocument();
  });

  it("has aria-label for estado", () => {
    render(<StatusBadge value="Publicada" />);
    expect(screen.getByLabelText("Estado: Publicada")).toBeInTheDocument();
  });
});

describe("StatusBadge — estado kind, código canónico", () => {
  // El detalle de una licitación pasa `l.estado`, que es el código de la
  // columna. Con el mapa indexado sólo por etiquetas la chapa salía neutra,
  // sin icono y rotulada "PUB".
  it("renders the label, not the raw code", () => {
    render(<StatusBadge value="PUB" />);
    expect(screen.getByText("Publicada")).toBeInTheDocument();
    expect(screen.queryByText("PUB")).not.toBeInTheDocument();
  });

  it("labels the states canonised in v91", () => {
    render(<StatusBadge value="AGR" />);
    expect(screen.getByText("Publicación agregada")).toBeInTheDocument();
  });

  it("uses the label in the aria-label too", () => {
    render(<StatusBadge value="ADJ" />);
    expect(screen.getByLabelText("Estado: Adjudicada")).toBeInTheDocument();
  });

  it("picks up the icon for a code", () => {
    const { container } = render(<StatusBadge value="ADJ" showIcon />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("leaves an unknown state as-is", () => {
    render(<StatusBadge value="FASE NUEVA" />);
    expect(screen.getByText("FASE NUEVA")).toBeInTheDocument();
  });
});

describe("StatusBadge — band kind", () => {
  it("renders Caliente band", () => {
    render(<StatusBadge value="Caliente" kind="band" />);
    expect(screen.getByText("Caliente")).toBeInTheDocument();
  });

  it("renders Atractiva band", () => {
    render(<StatusBadge value="Atractiva" kind="band" />);
    expect(screen.getByText("Atractiva")).toBeInTheDocument();
  });

  it("renders Tibia band", () => {
    render(<StatusBadge value="Tibia" kind="band" />);
    expect(screen.getByText("Tibia")).toBeInTheDocument();
  });

  it("renders Descarte band", () => {
    render(<StatusBadge value="Descarte" kind="band" />);
    expect(screen.getByText("Descarte")).toBeInTheDocument();
  });

  it("has aria-label for band", () => {
    render(<StatusBadge value="Caliente" kind="band" />);
    expect(screen.getByLabelText("Puntuación: Caliente")).toBeInTheDocument();
  });
});

describe("StatusBadge — showIcon", () => {
  it("renders without icon by default (showIcon=false)", () => {
    const { container } = render(<StatusBadge value="Publicada" />);
    // Should not render an SVG icon
    expect(container.querySelector("svg")).toBeNull();
  });

  it("renders with icon when showIcon=true and icon is available", () => {
    const { container } = render(<StatusBadge value="Publicada" showIcon />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("renders dot indicator when showIcon=false", () => {
    const { container } = render(<StatusBadge value="Publicada" showIcon={false} />);
    // The dot span has specific aria-hidden attribute
    expect(container.querySelector("[aria-hidden=true]")).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = render(<StatusBadge value="Publicada" className="extra-class" />);
    expect(container.firstChild).toHaveClass("extra-class");
  });
});
