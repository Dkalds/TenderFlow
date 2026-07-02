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

describe("DropdownMenu", () => {
  it("renders the trigger and items", () => {
    render(<Menu />);
    expect(screen.getByText("Abrir menú")).toBeInTheDocument();
    expect(screen.getByText("Editar")).toBeInTheDocument();
    expect(screen.getByText("Borrar")).toBeInTheDocument();
  });

  it("toggles the data-open attribute on the content when the trigger is clicked", () => {
    render(<Menu />);
    const content = screen.getByTestId("content");
    expect(content.hasAttribute("data-open")).toBe(false);
    fireEvent.click(screen.getByText("Abrir menú"));
    expect(content.hasAttribute("data-open")).toBe(true);
    fireEvent.click(screen.getByText("Abrir menú"));
    expect(content.hasAttribute("data-open")).toBe(false);
  });

  it("closes when clicking outside", () => {
    render(
      <div>
        <Menu />
        <button>fuera</button>
      </div>,
    );
    fireEvent.click(screen.getByText("Abrir menú"));
    expect(screen.getByTestId("content").hasAttribute("data-open")).toBe(true);
    fireEvent.click(screen.getByText("fuera"));
    expect(screen.getByTestId("content").hasAttribute("data-open")).toBe(false);
  });

  it("supports each alignment", () => {
    for (const align of ["start", "center", "end"] as const) {
      const { unmount } = render(<Menu align={align} />);
      expect(screen.getByTestId("content")).toBeInTheDocument();
      unmount();
    }
  });
});
