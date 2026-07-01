import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Separator } from "@/components/ui/separator";

describe("Separator", () => {
  it("renders with role=none when decorative (default)", () => {
    const { container } = render(<Separator />);
    // decorative defaults to true → role="none"
    expect(container.firstChild).toHaveAttribute("role", "none");
  });

  it("renders with role=separator when not decorative", () => {
    render(<Separator decorative={false} />);
    expect(screen.getByRole("separator")).toBeInTheDocument();
  });

  it("applies horizontal orientation classes by default", () => {
    const { container } = render(<Separator />);
    expect(container.firstChild).toHaveClass("h-[1px]");
    expect(container.firstChild).toHaveClass("w-full");
  });

  it("applies vertical orientation classes", () => {
    const { container } = render(<Separator orientation="vertical" />);
    expect(container.firstChild).toHaveClass("h-full");
    expect(container.firstChild).toHaveClass("w-[1px]");
  });

  it("sets aria-orientation only when not decorative", () => {
    render(<Separator decorative={false} orientation="vertical" />);
    expect(screen.getByRole("separator")).toHaveAttribute("aria-orientation", "vertical");
  });

  it("does not set aria-orientation when decorative", () => {
    const { container } = render(<Separator orientation="vertical" />);
    expect(container.firstChild).not.toHaveAttribute("aria-orientation");
  });

  it("applies a custom className", () => {
    const { container } = render(<Separator className="my-sep" />);
    expect(container.firstChild).toHaveClass("my-sep");
  });
});
