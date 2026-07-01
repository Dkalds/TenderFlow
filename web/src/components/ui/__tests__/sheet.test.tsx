import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetClose,
} from "@/components/ui/sheet";

describe("Sheet", () => {
  it("is closed by default and opens via the trigger (uncontrolled)", () => {
    render(
      <Sheet>
        <SheetTrigger>Abrir</SheetTrigger>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Título</SheetTitle>
            <SheetDescription>Descripción</SheetDescription>
          </SheetHeader>
        </SheetContent>
      </Sheet>,
    );
    expect(screen.queryByText("Título")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Abrir"));
    expect(screen.getByText("Título")).toBeInTheDocument();
    expect(screen.getByText("Descripción")).toBeInTheDocument();
  });

  it("closes when the overlay is clicked", () => {
    render(
      <Sheet>
        <SheetTrigger>Abrir</SheetTrigger>
        <SheetContent>
          <SheetTitle>Panel</SheetTitle>
        </SheetContent>
      </Sheet>,
    );
    fireEvent.click(screen.getByText("Abrir"));
    const overlay = document.querySelector('[role="presentation"]')!;
    fireEvent.click(overlay);
    expect(screen.queryByText("Panel")).not.toBeInTheDocument();
  });

  it("supports controlled open state with onOpenChange", () => {
    const { rerender } = render(
      <Sheet open={true} onOpenChange={() => {}}>
        <SheetContent side="left">
          <SheetTitle>Controlado</SheetTitle>
          <SheetClose>Cerrar</SheetClose>
        </SheetContent>
      </Sheet>,
    );
    expect(screen.getByText("Controlado")).toBeInTheDocument();
    rerender(
      <Sheet open={false} onOpenChange={() => {}}>
        <SheetContent side="left">
          <SheetTitle>Controlado</SheetTitle>
        </SheetContent>
      </Sheet>,
    );
    expect(screen.queryByText("Controlado")).not.toBeInTheDocument();
  });

  it("renders the different sides without throwing", () => {
    for (const side of ["top", "bottom", "left", "right"] as const) {
      const { unmount } = render(
        <Sheet open>
          <SheetContent side={side}>
            <SheetTitle>{`side-${side}`}</SheetTitle>
          </SheetContent>
        </Sheet>,
      );
      expect(screen.getByText(`side-${side}`)).toBeInTheDocument();
      unmount();
    }
  });
});
