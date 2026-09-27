import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge } from "@/components/ui/badge";

describe("Badge", () => {
  it("renders children text", () => {
    render(<Badge>Activo</Badge>);
    expect(screen.getByText("Activo")).toBeInTheDocument();
  });

  it("renders with default variant", () => {
    const { container } = render(<Badge>default</Badge>);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("renders with secondary variant", () => {
    const { container } = render(<Badge variant="secondary">sec</Badge>);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("renders with destructive variant", () => {
    const { container } = render(<Badge variant="destructive">del</Badge>);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("renders with success variant", () => {
    const { container } = render(<Badge variant="success">ok</Badge>);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("renders with warning variant", () => {
    render(<Badge variant="warning">warn</Badge>);
    expect(screen.getByText("warn")).toBeInTheDocument();
  });

  it("renders with info variant", () => {
    render(<Badge variant="info">info</Badge>);
    expect(screen.getByText("info")).toBeInTheDocument();
  });

  it("renders with outline variant", () => {
    render(<Badge variant="outline">outline</Badge>);
    expect(screen.getByText("outline")).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = render(<Badge className="custom-class">x</Badge>);
    expect(container.firstChild).toHaveClass("custom-class");
  });

  it("es un span: puede ir dentro de un párrafo", () => {
    // Un `div` dentro de un `<p>` es HTML inválido y React avisa al hidratar.
    const { container } = render(<Badge>test</Badge>);
    expect(container.firstChild?.nodeName).toBe("SPAN");
  });

  it("no finge ser interactivo: sin hover, foco, transición ni sombra", () => {
    const { container } = render(<Badge>x</Badge>);
    const clases = (container.firstChild as HTMLElement).className;
    expect(clases).not.toMatch(/hover:|focus:|transition|shadow/);
  });

  it("por defecto es neutral, no el primario macizo de shadcn", () => {
    const { container } = render(<Badge>x</Badge>);
    const clases = (container.firstChild as HTMLElement).className;
    expect(clases).toContain("bg-muted-foreground/10");
    expect(clases).not.toContain("bg-primary ");
  });

  it("los tonos son un tinte al 10 % con el texto del tono", () => {
    const { container } = render(<Badge variant="warning">w</Badge>);
    expect(container.firstChild).toHaveClass("bg-warning/10", "text-warning", "border-warning/30");
  });

  it("la talla sm baja a 11 px", () => {
    const { container } = render(<Badge size="sm">x</Badge>);
    expect(container.firstChild).toHaveClass("text-tf-micro", "h-5");
  });
});
