import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Switch } from "@/components/ui/switch";

describe("Switch", () => {
  it("renders a switch element", () => {
    render(<Switch aria-label="modo oscuro" />);
    expect(screen.getByRole("switch")).toBeInTheDocument();
  });

  it("is unchecked by default", () => {
    render(<Switch aria-label="s" />);
    expect(screen.getByRole("switch")).toHaveAttribute("data-state", "unchecked");
  });

  it("renders checked when defaultChecked is set", () => {
    render(<Switch aria-label="s" defaultChecked />);
    expect(screen.getByRole("switch")).toHaveAttribute("data-state", "checked");
  });

  it("fires onCheckedChange when toggled", () => {
    const handler = vi.fn();
    render(<Switch aria-label="s" onCheckedChange={handler} />);
    fireEvent.click(screen.getByRole("switch"));
    expect(handler).toHaveBeenCalledWith(true);
  });

  it("can be disabled", () => {
    render(<Switch aria-label="s" disabled />);
    expect(screen.getByRole("switch")).toBeDisabled();
  });

  it("does not fire onCheckedChange when disabled", () => {
    const handler = vi.fn();
    render(<Switch aria-label="s" disabled onCheckedChange={handler} />);
    fireEvent.click(screen.getByRole("switch"));
    expect(handler).not.toHaveBeenCalled();
  });

  it("applies a custom className", () => {
    render(<Switch aria-label="s" className="my-switch" />);
    expect(screen.getByRole("switch")).toHaveClass("my-switch");
  });
});
