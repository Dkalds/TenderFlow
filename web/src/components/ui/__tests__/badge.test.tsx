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

  it("renders as a div element", () => {
    const { container } = render(<Badge>test</Badge>);
    expect(container.firstChild?.nodeName).toBe("DIV");
  });
});
