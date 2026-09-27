/**
 * El toast es la tarjeta de la app, no la demo de Sonner: sin `richColors`,
 * con iconos de contorno del color del tipo y la superficie desde los tokens.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, act, cleanup } from "@testing-library/react";
import { toast } from "sonner";

vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));

import { Toaster } from "@/components/toaster";

afterEach(() => {
  act(() => {
    toast.dismiss();
  });
  cleanup();
});

describe("Toaster", () => {
  it("no usa la paleta de demostración de Sonner (richColors)", async () => {
    render(<Toaster />);
    act(() => {
      toast.error("No se pudo guardar");
    });
    const titulo = await screen.findByText("No se pudo guardar");
    const caja = titulo.closest("[data-sonner-toast]");
    expect(caja).not.toBeNull();
    expect(caja).not.toHaveAttribute("data-rich-colors", "true");
  });

  it("el icono es el de contorno del tipo, con su color", async () => {
    render(<Toaster />);
    act(() => {
      toast.error("Falló");
    });
    const caja = (await screen.findByText("Falló")).closest("[data-sonner-toast]");
    const icono = caja?.querySelector("[data-icon] svg");
    expect(icono).not.toBeNull();
    expect(icono).toHaveClass("text-destructive");
    expect(icono).toHaveAttribute("aria-hidden", "true");
  });

  it("cada tipo lleva su icono de contorno y su color", async () => {
    render(<Toaster />);
    act(() => {
      toast.success("Guardado");
      toast.warning("Cuidado");
      toast.info("Para que lo sepas");
    });
    const icono = async (texto: string) =>
      (await screen.findByText(texto)).closest("[data-sonner-toast]")?.querySelector("[data-icon] svg");
    expect(await icono("Guardado")).toHaveClass("lucide-circle-check", "text-success");
    expect(await icono("Cuidado")).toHaveClass("lucide-triangle-alert", "text-warning");
    expect(await icono("Para que lo sepas")).toHaveClass("lucide-info", "text-info");
  });

  it("la superficie no va en clases del toast: la pone globals.css con los tokens", async () => {
    render(<Toaster />);
    act(() => {
      toast.success("Guardado");
    });
    const caja = (await screen.findByText("Guardado")).closest("[data-sonner-toast]");
    // Una utilidad de Tailwind pierde contra la hoja de Sonner (sin capa): si
    // alguien vuelve a pasar `toastOptions.classNames`, no pintaría nada.
    expect(caja?.className ?? "").not.toMatch(/--normal-|shadow-|text-muted-foreground/);

    const hoja = readFileSync(path.resolve(__dirname, "../../app/globals.css"), "utf8");
    const piel = hoja.match(/html \[data-sonner-toaster\]\[data-sonner-theme\] \{([^}]*)\}/)?.[1] ?? "";
    expect(piel).toContain("--normal-bg: hsl(var(--card))");
    expect(piel).toContain("--normal-border: hsl(var(--border))");
    expect(piel).toContain("--normal-text: hsl(var(--card-foreground))");
  });
});
