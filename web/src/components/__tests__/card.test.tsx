import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card";

describe("Card", () => {
  it("renders a full card composition", () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>Título</CardTitle>
          <CardDescription>Descripción</CardDescription>
        </CardHeader>
        <CardContent>Contenido</CardContent>
        <CardFooter>Pie</CardFooter>
      </Card>,
    );
    expect(screen.getByText("Título")).toBeInTheDocument();
    expect(screen.getByText("Descripción")).toBeInTheDocument();
    expect(screen.getByText("Contenido")).toBeInTheDocument();
    expect(screen.getByText("Pie")).toBeInTheDocument();
  });

  it("Card applies a custom className", () => {
    const { container } = render(<Card className="my-card" />);
    expect(container.firstChild).toHaveClass("my-card");
  });

  it("CardHeader applies a custom className", () => {
    const { container } = render(<CardHeader className="my-header" />);
    expect(container.firstChild).toHaveClass("my-header");
  });

  it("CardTitle applies a custom className", () => {
    const { container } = render(<CardTitle className="my-title" />);
    expect(container.firstChild).toHaveClass("my-title");
  });

  it("CardDescription applies a custom className", () => {
    const { container } = render(<CardDescription className="my-desc" />);
    expect(container.firstChild).toHaveClass("my-desc");
  });

  it("CardContent applies a custom className", () => {
    const { container } = render(<CardContent className="my-content" />);
    expect(container.firstChild).toHaveClass("my-content");
  });

  it("CardFooter applies a custom className", () => {
    const { container } = render(<CardFooter className="my-footer" />);
    expect(container.firstChild).toHaveClass("my-footer");
  });

  it("forwards ref on Card", () => {
    const ref = { current: null as HTMLDivElement | null };
    render(<Card ref={ref} />);
    expect(ref.current?.tagName).toBe("DIV");
  });

  it("forwards ref on CardContent", () => {
    const ref = { current: null as HTMLDivElement | null };
    render(<CardContent ref={ref} />);
    expect(ref.current?.tagName).toBe("DIV");
  });

  it("renders children inside CardContent", () => {
    render(<CardContent><span>inner</span></CardContent>);
    expect(screen.getByText("inner")).toBeInTheDocument();
  });
});
