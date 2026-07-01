import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Slider } from "@/components/ui/slider";

describe("Slider", () => {
  it("renders a slider element", () => {
    render(<Slider aria-label="importe" defaultValue={[50]} max={100} />);
    expect(screen.getByRole("slider")).toBeInTheDocument();
  });

  it("reflects the default value on the thumb", () => {
    render(<Slider aria-label="importe" defaultValue={[30]} max={100} />);
    expect(screen.getByRole("slider")).toHaveAttribute("aria-valuenow", "30");
  });

  it("honours the max attribute", () => {
    render(<Slider aria-label="importe" defaultValue={[10]} max={200} />);
    expect(screen.getByRole("slider")).toHaveAttribute("aria-valuemax", "200");
  });

  it("honours the min attribute", () => {
    render(<Slider aria-label="importe" defaultValue={[10]} min={5} max={100} />);
    expect(screen.getByRole("slider")).toHaveAttribute("aria-valuemin", "5");
  });

  it("can be disabled", () => {
    const { container } = render(
      <Slider aria-label="importe" defaultValue={[50]} max={100} disabled />,
    );
    // Radix marks the root with data-disabled when disabled
    expect(container.querySelector("[data-disabled]")).toBeInTheDocument();
  });

  it("applies a custom className to the root", () => {
    const { container } = render(
      <Slider aria-label="importe" defaultValue={[50]} max={100} className="my-slider" />,
    );
    expect(container.firstChild).toHaveClass("my-slider");
  });

  it("renders a thumb for a single-value slider", () => {
    render(<Slider aria-label="valor" defaultValue={[40]} max={100} />);
    expect(screen.getAllByRole("slider")).toHaveLength(1);
  });
});
