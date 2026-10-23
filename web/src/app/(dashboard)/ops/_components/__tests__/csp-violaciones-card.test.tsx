import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * La tarjeta enseña lo que la CSP bloqueó **agrupado** —directiva y origen—
 * y en una ventana que dice: el número que importa es cuántas veces, no
 * cuántos informes. Y un vacío es «nada bloqueado en la ventana», que no es lo
 * mismo que «no se pudo cargar».
 */

// Solo se sustituye `apiGet`: `PanelError` necesita el `ApiError` real del
// módulo para clasificar el fallo que pinta.
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiGet: vi.fn(),
}));

import { CspViolacionesCard } from "@/app/(dashboard)/ops/_components/observabilidad/csp-violaciones-card";
import { TooltipProvider } from "@/components/ui/tooltip";
import { apiGet } from "@/lib/api-client";

const pedir = vi.mocked(apiGet);

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  // `Pista` monta un tooltip de Radix: en la consola lo provee el layout.
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <CspViolacionesCard />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("CspViolacionesCard", () => {
  beforeEach(() => {
    cleanup();
    pedir.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("pide la ventana y el tope, y enseña cada grupo con sus veces", async () => {
    pedir.mockResolvedValue({
      dias: 7,
      items: [
        {
          directiva: "frame-src",
          origen: "https://www.youtube.com",
          documento: "https://app.example/detalle",
          ocurrencias: 14,
          primera_vez: "2026-10-02T10:00:00Z",
          ultima_vez: "2026-10-09T10:00:00Z",
        },
      ],
    });
    renderCard();

    expect(await screen.findByText("frame-src")).toBeInTheDocument();
    expect(pedir).toHaveBeenCalledWith(
      "/api/v1/security/csp-violations",
      expect.objectContaining({ params: { query: { limit: 20, dias: 7 } } }),
    );
    expect(screen.getByText("https://www.youtube.com")).toBeInTheDocument();
    expect(screen.getByText("https://app.example/detalle")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();
    expect(screen.getByText(/en los últimos 7 días/)).toBeInTheDocument();
  });

  it("sin bloqueos lo dice, en vez de dejar la tabla vacía", async () => {
    pedir.mockResolvedValue({ dias: 7, items: [] });
    renderCard();

    expect(await screen.findByText("Ningún bloqueo en la ventana")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("con la consulta caída no afirma que no haya bloqueos", async () => {
    pedir.mockRejectedValue(new Error("fetch failed"));
    renderCard();

    expect(
      await screen.findByText("No se pudieron cargar los bloqueos de la política de contenido"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Ningún bloqueo en la ventana")).not.toBeInTheDocument();
  });
});
