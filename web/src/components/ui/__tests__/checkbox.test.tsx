import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Checkbox } from "@/components/ui/checkbox";

describe("Checkbox", () => {
  it("renders a checkbox element", () => {
    render(<Checkbox aria-label="acepto" />);
    expect(screen.getByRole("checkbox")).toBeInTheDocument();
  });

  it("is unchecked by default", () => {
    render(<Checkbox aria-label="acepto" />);
    expect(screen.getByRole("checkbox")).toHaveAttribute("data-state", "unchecked");
  });

  it("renders as checked when defaultChecked is set", () => {
    render(<Checkbox aria-label="acepto" defaultChecked />);
    expect(screen.getByRole("checkbox")).toHaveAttribute("data-state", "checked");
  });

  it("fires onCheckedChange when clicked", () => {
    const handler = vi.fn();
    render(<Checkbox aria-label="acepto" onCheckedChange={handler} />);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(handler).toHaveBeenCalledWith(true);
  });

  it("can be disabled", () => {
    render(<Checkbox aria-label="acepto" disabled />);
    expect(screen.getByRole("checkbox")).toBeDisabled();
  });

  it("does not fire onCheckedChange when disabled", () => {
    const handler = vi.fn();
    render(<Checkbox aria-label="acepto" disabled onCheckedChange={handler} />);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(handler).not.toHaveBeenCalled();
  });

  it("follows the controlled checked prop and exposes aria-checked", () => {
    const { rerender } = render(<Checkbox aria-label="acepto" checked={false} />);
    expect(screen.getByRole("checkbox")).toHaveAttribute("aria-checked", "false");
    rerender(<Checkbox aria-label="acepto" checked />);
    expect(screen.getByRole("checkbox")).toHaveAttribute("aria-checked", "true");
  });

  it("does not toggle on Enter (WAI-ARIA: Space toggles a checkbox)", () => {
    render(<Checkbox aria-label="acepto" />);
    const casilla = screen.getByRole("checkbox");
    expect(fireEvent.keyDown(casilla, { key: "Enter" })).toBe(false);
  });

  it("lets onClick cancel the toggle with preventDefault", () => {
    const handler = vi.fn();
    render(
      <Checkbox aria-label="acepto" onClick={(e) => e.preventDefault()} onCheckedChange={handler} />
    );
    fireEvent.click(screen.getByRole("checkbox"));
    expect(handler).not.toHaveBeenCalled();
  });

  it("applies a custom className", () => {
    render(<Checkbox aria-label="acepto" className="my-checkbox" />);
    expect(screen.getByRole("checkbox")).toHaveClass("my-checkbox");
  });
});
