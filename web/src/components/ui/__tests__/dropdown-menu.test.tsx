import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";

function Menu({ align }: { align?: "start" | "center" | "end" }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger>Abrir menú</DropdownMenuTrigger>
      <DropdownMenuContent align={align} data-testid="content">
        <DropdownMenuItem>Editar</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem inset>Borrar</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// Radix's DropdownMenu trigger opens on pointer down (not on a synthetic
// `click`), so tests drive it via a pointerDown+pointerUp pair like a real
// pointer interaction would produce.
function openMenu(trigger: HTMLElement) {
  fireEvent.pointerDown(trigger, { button: 0, pointerId: 1, pointerType: "mouse" });
  fireEvent.pointerUp(trigger, { button: 0, pointerId: 1, pointerType: "mouse" });
}

describe("DropdownMenu", () => {
  it("renders the trigger, and the items after opening", () => {
    render(<Menu />);
    expect(screen.getByText("Abrir menú")).toBeInTheDocument();
    // Radix only mounts DropdownMenuContent in the DOM while open (via a
    // portal), unlike the previous hand-rolled version which always rendered
    // it and toggled a `hidden` class.
    expect(screen.queryByText("Editar")).not.toBeInTheDocument();
    openMenu(screen.getByText("Abrir menú"));
    expect(screen.getByText("Editar")).toBeInTheDocument();
    expect(screen.getByText("Borrar")).toBeInTheDocument();
  });

  it("toggles the menu open and closed when the trigger is activated twice", () => {
    render(<Menu />);
    const trigger = screen.getByText("Abrir menú");
    expect(screen.queryByTestId("content")).not.toBeInTheDocument();
    openMenu(trigger);
    expect(screen.getByTestId("content")).toBeInTheDocument();
    expect(screen.getByRole("menu")).toBeInTheDocument();
    openMenu(trigger);
    expect(screen.queryByTestId("content")).not.toBeInTheDocument();
  });

  it("closes on Escape", () => {
    render(<Menu />);
    openMenu(screen.getByText("Abrir menú"));
    expect(screen.getByTestId("content")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByTestId("content"), { key: "Escape" });
    expect(screen.queryByTestId("content")).not.toBeInTheDocument();
  });

  it("supports each alignment", () => {
    for (const align of ["start", "center", "end"] as const) {
      const { unmount } = render(<Menu align={align} />);
      openMenu(screen.getByText("Abrir menú"));
      expect(screen.getByTestId("content")).toBeInTheDocument();
      unmount();
    }
  });
});
