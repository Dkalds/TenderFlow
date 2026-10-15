/**
 * El 403 de «vuelve a entrar» no es un 403 de permiso.
 *
 * Las acciones sensibles —activar o quitar el segundo factor, acuñar, rotar o
 * revocar claves, borrar una organización— exigen una sesión reciente. Pasado
 * ese margen la API responde 403 con un tipo propio, y la consola ofrece
 * volver a entrar en vez de decir «no tienes permiso», que sería falso.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { apiMutate } = vi.hoisted(() => ({ apiMutate: vi.fn() }));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiMutate,
}));

import { ApiError } from "@/lib/api-client";
import { AvisoReautenticacion } from "@/components/console/aviso-reautenticacion";
import { destinoTrasVolver, pideReautenticacion, TIPO_REAUTENTICACION } from "@/lib/reautenticacion";

afterEach(() => {
  vi.clearAllMocks();
});

describe("pideReautenticacion", () => {
  it("reconoce el 403 de sesión antigua por su tipo", () => {
    expect(pideReautenticacion(new ApiError(403, "Reauthenticate…", TIPO_REAUTENTICACION))).toBe(true);
  });

  it("un 403 de permiso, o cualquier otro fallo, no", () => {
    expect(pideReautenticacion(new ApiError(403, "Admin required."))).toBe(false);
    expect(pideReautenticacion(new ApiError(400, "x", TIPO_REAUTENTICACION))).toBe(false);
    expect(pideReautenticacion(new Error("x"))).toBe(false);
    expect(pideReautenticacion(null)).toBe(false);
  });
});

describe("destinoTrasVolver", () => {
  it("vuelve a la misma pantalla y vista tras entrar", () => {
    expect(destinoTrasVolver("/ajustes", "?vista=seguridad")).toBe(
      "/login?redirect=%2Fajustes%3Fvista%3Dseguridad",
    );
  });
});

describe("AvisoReautenticacion", () => {
  it("explica el motivo y cierra la sesión antes de llevar al login", async () => {
    apiMutate.mockResolvedValue({ detail: "Logged out" });
    const irA = vi.fn();
    render(<AvisoReautenticacion accion="activar la verificación en dos pasos" irA={irA} />);

    expect(screen.getByText(/Vuelve a entrar para activar la verificación en dos pasos/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Volver a entrar" }));

    await waitFor(() => expect(irA).toHaveBeenCalled());
    // Sin cerrar la sesión, el login vería la cookie viva y ofrecería «Continuar»
    // con la misma sesión antigua: el 403 volvería a salir.
    expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/auth/logout");
    expect(irA.mock.calls[0][0]).toMatch(/^\/login\?redirect=/);
  });
});
