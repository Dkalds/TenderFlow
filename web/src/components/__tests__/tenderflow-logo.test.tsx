import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TenderFlowLogo, TenderFlowIcon } from "@/components/layout/tenderflow-logo";

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
});

describe("TenderFlowIcon", () => {
  it("renders the icon-only variant without the wordmark", () => {
    render(<TenderFlowIcon />);
    expect(screen.queryByText("TenderFlow")).toBeNull();
  });

  it("renders an svg mark", () => {
    const { container } = render(<TenderFlowIcon />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("uses a custom size", () => {
    const { container } = render(<TenderFlowIcon size={48} />);
    const svg = container.querySelector("svg");
    // iconSize = round(48 * 0.58) = 28
    expect(svg).toHaveAttribute("width", "28");
  });
});
