/**
 * `toast()` sin Sonner en el First Load: lo que se pide antes de que Sonner
 * llegue se entrega al llegar, en orden; después, la llamada es directa.
 */
import { describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => {
  const sonner = Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    dismiss: vi.fn(),
  });
  return { sonner };
});

vi.mock("sonner", () => ({ toast: h.sonner }));

import { cargarSonner, toast } from "@/lib/toast";

describe("toast diferido", () => {
  it("guarda las llamadas hasta que llega Sonner y las entrega en orden", async () => {
    toast.success("Guardado", { description: "detalle" });
    toast("Regla en pausa");
    toast.error("Falló");
    expect(h.sonner.success).not.toHaveBeenCalled();

    await cargarSonner();

    expect(h.sonner.success).toHaveBeenCalledWith("Guardado", { description: "detalle" });
    expect(h.sonner).toHaveBeenCalledWith("Regla en pausa");
    expect(h.sonner.error).toHaveBeenCalledWith("Falló");
    expect(h.sonner.success.mock.invocationCallOrder[0]).toBeLessThan(h.sonner.mock.invocationCallOrder[0]);
  });

  it("con Sonner ya cargado, la llamada es inmediata", async () => {
    await cargarSonner();
    toast.warning("Cuidado");
    toast.dismiss();
    expect(h.sonner.warning).toHaveBeenCalledWith("Cuidado");
    expect(h.sonner.dismiss).toHaveBeenCalledWith(undefined);
  });
});
