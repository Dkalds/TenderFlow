/**
 * El botón de Microsoft con su bandera puesta.
 *
 * Va en su propio fichero porque `MICROSOFT_HABILITADO` se resuelve al evaluar
 * el módulo: la variable tiene que estar en el entorno **antes** del import, y
 * eso es justo lo que `vi.hoisted` garantiza. Hacerlo dentro del fichero
 * principal habría exigido `vi.resetModules()` + import dinámico, que reevalúa
 * React y deja dos copias en la misma prueba.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.hoisted(() => {
  process.env.NEXT_PUBLIC_OAUTH_MICROSOFT = "1";
});

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/analytics", () => ({
  registrarEvento: vi.fn(),
  primeraVez: vi.fn(),
}));

import LoginPage from "@/app/login/page";

describe("acceso con Microsoft", () => {
  it("se ofrece junto a Google cuando el despliegue lo declara", () => {
    render(<LoginPage />);

    const google = screen.getByRole("button", { name: "Continuar con Google" });
    const microsoft = screen.getByRole("button", { name: "Continuar con Microsoft" });

    // Google primero: es el proveedor con el que entra la mayoría y el orden
    // de la tarjeta es parte de lo que el troceado no podía cambiar.
    expect(google.compareDocumentPosition(microsoft) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
