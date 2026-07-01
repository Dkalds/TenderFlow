import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Button } from "@/components/ui/button";

describe("Button", () => {
  it("renders children text", () => {
    render(<Button>Guardar</Button>);
    expect(screen.getByRole("button", { name: "Guardar" })).toBeInTheDocument();
  });

  it("is a button element by default", () => {
    render(<Button>click me</Button>);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("renders with default variant", () => {
    const { container } = render(<Button>default</Button>);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("renders with destructive variant", () => {
    render(<Button variant="destructive">delete</Button>);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("renders with outline variant", () => {
    render(<Button variant="outline">outline</Button>);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("renders with secondary variant", () => {
    render(<Button variant="secondary">sec</Button>);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("renders with ghost variant", () => {
    render(<Button variant="ghost">ghost</Button>);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("renders with link variant", () => {
    render(<Button variant="link">link</Button>);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("renders with sm size", () => {
    render(<Button size="sm">small</Button>);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("renders with lg size", () => {
    render(<Button size="lg">large</Button>);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("renders with icon size", () => {
    render(<Button size="icon">x</Button>);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("fires onClick handler", () => {
    const handler = vi.fn();
    render(<Button onClick={handler}>click</Button>);
    fireEvent.click(screen.getByRole("button"));
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("is disabled when disabled prop is set", () => {
    render(<Button disabled>disabled</Button>);
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("does not fire onClick when disabled", () => {
    const handler = vi.fn();
    render(
      <Button disabled onClick={handler}>
        no-click
      </Button>,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(handler).not.toHaveBeenCalled();
  });

  it("applies custom className", () => {
    const { container } = render(<Button className="my-class">x</Button>);
    expect(container.firstChild).toHaveClass("my-class");
  });

  it("forwards ref to button element", () => {
    const ref = { current: null as HTMLButtonElement | null };
    render(<Button ref={ref}>ref</Button>);
    expect(ref.current).not.toBeNull();
    expect(ref.current?.tagName).toBe("BUTTON");
  });
});
