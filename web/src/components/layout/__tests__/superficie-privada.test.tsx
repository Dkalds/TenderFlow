import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * `SuperficiePrivada` es la pila común de los tres layouts con sesión. Lo que
 * fija este test es el invariante que motivó unificarla: el `Toaster` y la
 * región viva existen en cualquier superficie que la use (un `toast()` en
 * `/login` llegó a perderse porque el `Toaster` sólo estaba en el dashboard), y
 * los providers reciben el nonce de la CSP.
 */

const cabeceras = vi.hoisted(() => ({ actual: new Headers() }));
vi.mock("next/headers", () => ({ headers: async () => cabeceras.actual }));

const nonces: Array<string | undefined> = [];
vi.mock("@/components/providers", () => ({
  Providers: ({ children, nonce }: { children: React.ReactNode; nonce?: string }) => {
    nonces.push(nonce);
    return <div data-testid="providers">{children}</div>;
  },
}));
vi.mock("@/components/route-progress", () => ({ RouteProgress: () => <span>progreso</span> }));
vi.mock("@/components/toaster", () => ({ Toaster: () => <span>toaster</span> }));
vi.mock("@/components/live-region", () => ({ LiveRegion: () => <span>region-viva</span> }));

import { SuperficiePrivada } from "@/components/layout/superficie-privada";

describe("SuperficiePrivada", () => {
  it("monta providers, progreso, Toaster y región viva alrededor del contenido", async () => {
    cabeceras.actual = new Headers({ "x-nonce": "n0nce" });

    render(await SuperficiePrivada({ children: <p>contenido</p> }));

    const providers = screen.getByTestId("providers");
    for (const texto of ["progreso", "contenido", "toaster", "region-viva"]) {
      expect(providers).toContainElement(screen.getByText(texto));
    }
    expect(nonces.at(-1)).toBe("n0nce");
  });

  it("sin nonce en la request los providers reciben undefined, no una cadena vacía", async () => {
    cabeceras.actual = new Headers();

    render(await SuperficiePrivada({ children: null }));

    expect(nonces.at(-1)).toBeUndefined();
  });
});
