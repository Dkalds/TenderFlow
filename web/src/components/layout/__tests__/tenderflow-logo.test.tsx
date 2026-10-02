import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TenderFlowLogo } from "@/components/layout/tenderflow-logo";
import { TF_MARK_PATHS } from "@/lib/marca";

describe("TenderFlowLogo", () => {
  it("renders the wordmark by default", () => {
    render(<TenderFlowLogo />);
    expect(screen.getByText("TenderFlow")).toBeInTheDocument();
    expect(screen.getByText("Sector público")).toBeInTheDocument();
  });

  it("hides the wordmark when showText is false", () => {
    render(<TenderFlowLogo showText={false} />);
    expect(screen.queryByText("TenderFlow")).toBeNull();
    expect(screen.queryByText("Sector público")).toBeNull();
  });

  it("renders the TF mark svg", () => {
    const { container } = render(<TenderFlowLogo />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("respects a custom boxSize (icon scales with it)", () => {
    const { container } = render(<TenderFlowLogo boxSize={64} />);
    const svg = container.querySelector("svg");
    // iconSize = round(64 * 0.58) = 37
    expect(svg).toHaveAttribute("width", "37");
    expect(svg).toHaveAttribute("height", "37");
  });

  it("applies a custom className to the wrapper", () => {
    const { container } = render(<TenderFlowLogo className="my-logo" />);
    expect(container.firstChild).toHaveClass("my-logo");
  });

  it("marks the svg as aria-hidden (decorative)", () => {
    const { container } = render(<TenderFlowLogo />);
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("dibuja el trazo de lib/marca, no una copia propia", () => {
    const { container } = render(<TenderFlowLogo />);
    const trazos = Array.from(container.querySelectorAll("path")).map((p) => p.getAttribute("d"));
    expect(trazos).toEqual([...TF_MARK_PATHS]);
  });

  it("la caja de la marca va plana: sin halo de color ni sombra", () => {
    const { container } = render(<TenderFlowLogo />);
    const caja = container.querySelector("svg")?.parentElement;
    expect(caja?.className).not.toMatch(/shadow/);
  });

  it("el wordmark va en la fuente display y la línea de sector en frase, sin versal", () => {
    render(<TenderFlowLogo />);
    expect(screen.getByText("TenderFlow")).toHaveClass("font-display");
    const sector = screen.getByText("Sector público");
    expect(sector.className).not.toMatch(/uppercase|tracking-/);
  });
});
