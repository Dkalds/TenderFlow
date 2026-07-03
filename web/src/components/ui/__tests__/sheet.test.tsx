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

  it("renders an overlay backdrop while open", () => {
    render(
      <Sheet>
        <SheetTrigger>Abrir</SheetTrigger>
        <SheetContent>
          <SheetTitle>Panel</SheetTitle>
        </SheetContent>
      </Sheet>,
    );
    fireEvent.click(screen.getByText("Abrir"));
    // Radix's Dialog.Overlay renders without an ARIA role (it's a purely
    // visual backdrop); select it by its distinguishing class instead of
    // `[role="presentation"]` used by the previous hand-rolled overlay.
    expect(document.querySelector(".fixed.inset-0.bg-black\\/80")).toBeInTheDocument();
  });

  it("closes on Escape (Radix's built-in dismiss behavior)", () => {
    render(
      <Sheet>
        <SheetTrigger>Abrir</SheetTrigger>
        <SheetContent>
          <SheetTitle>Panel</SheetTitle>
        </SheetContent>
      </Sheet>,
    );
    fireEvent.click(screen.getByText("Abrir"));
    expect(screen.getByText("Panel")).toBeInTheDocument();
    // Real pointer-outside-click dismissal relies on Radix's DismissableLayer
    // capturing a native pointerdown on `document`, which jsdom + fireEvent's
    // synthetic events cannot reproduce reliably; Escape is the deterministic
    // way to exercise the same dismiss codepath (`onOpenChange(false)`) here.
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
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
