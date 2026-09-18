/**
 * Los dos formularios de reglas con el esquema de `WatchlistRuleBody` (S7.2):
 * el alta rápida y el panel de edición. Se montan sobre la página entera
 * porque el estado del alta vive en `useMiWatchlist`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: vi.fn() }),
}));

import MiWatchlistPage from "@/app/(dashboard)/mi-watchlist/page";

const RULE = {
  id: 42,
  nombre: "SAP",
  keyword: "SAP",
  cpv: null,
  min_importe: null,
  ccaa: null,
  frequency: "daily" as const,
  active: true,
  match_count: 7,
  email: null,
};

const peticiones: Array<{ method: string; url: string; body: Record<string, unknown> }> = [];

function montar() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method !== "GET") {
        peticiones.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : {} });
      }
      const cuerpo = url === "/api/v1/watchlist/rules" && method === "GET" ? { items: [RULE] } : { items: [] };
      return { ok: true, status: 200, json: async () => cuerpo };
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <MiWatchlistPage />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  peticiones.length = 0;
  vi.unstubAllGlobals();
});

describe("Nueva regla", () => {
  it("un importe negativo se explica debajo del campo y no crea nada", async () => {
    montar();
    fireEvent.change(screen.getByLabelText("Palabra clave *"), { target: { value: "SAP" } });
    const importe = screen.getByLabelText("Importe mínimo");
    fireEvent.change(importe, { target: { value: "-5" } });
    fireEvent.click(screen.getByRole("button", { name: /Agregar regla/ }));

    const error = await screen.findByText(/Escribe un importe en euros/);
    expect(error).toHaveAttribute("id", "wl-importe-error");
    expect(importe).toHaveAttribute("aria-describedby", "wl-importe-error");
    expect(peticiones).toEqual([]);
  });

  it("Enter sin palabra clave avisa en el campo en vez de callar", async () => {
    montar();
    const keyword = screen.getByLabelText("Palabra clave *");
    fireEvent.keyDown(keyword, { key: "Enter" });

    expect(await screen.findByText("Escribe una palabra clave.")).toHaveAttribute("id", "wl-keyword-error");
    expect(keyword).toHaveAttribute("aria-invalid", "true");
    expect(peticiones).toEqual([]);
  });

  it("crea con las claves del DTO y vacía el formulario", async () => {
    montar();
    const keyword = screen.getByLabelText("Palabra clave *");
    fireEvent.change(keyword, { target: { value: " SAP " } });
    fireEvent.change(screen.getByLabelText("Importe mínimo"), { target: { value: "1500.5" } });
    fireEvent.click(screen.getByRole("button", { name: /Agregar regla/ }));

    await waitFor(() => expect(peticiones).toHaveLength(1));
    expect(peticiones[0]).toMatchObject({
      method: "POST",
      url: "/api/v1/watchlist/rules",
      body: { nombre: "SAP", keyword: "SAP", cpv: null, min_importe: 1500.5, frequency: "daily" },
    });
    await waitFor(() => expect(keyword).toHaveValue(""));
  });
});

describe("Editar regla", () => {
  async function abrirEdicion() {
    montar();
    fireEvent.click(await screen.findByRole("button", { name: "Editar regla" }));
    return within(await screen.findByRole("dialog"));
  }

  it("un plazo fuera de 0-365 no se guarda y su error va antes que la nota", async () => {
    const dialogo = await abrirEdicion();
    const plazo = dialogo.getByLabelText("Plazo mínimo (días)");
    fireEvent.change(plazo, { target: { value: "400" } });
    fireEvent.click(dialogo.getByRole("button", { name: "Guardar cambios" }));

    expect(await dialogo.findByText("Escribe un número entero entre 0 y 365.")).toHaveAttribute(
      "id",
      "edit-wl-plazo-error",
    );
    expect(plazo).toHaveAttribute("aria-describedby", "edit-wl-plazo-error edit-wl-plazo-note");
    expect(peticiones).toEqual([]);

    // Tras el primer intento revalida al escribir: corregirlo quita el error.
    fireEvent.change(plazo, { target: { value: "15" } });
    await waitFor(() => expect(dialogo.queryByText(/número entero entre 0 y 365/)).toBeNull());
    expect(plazo).toHaveAttribute("aria-describedby", "edit-wl-plazo-note");

    fireEvent.click(dialogo.getByRole("button", { name: "Guardar cambios" }));
    await waitFor(() => expect(peticiones).toHaveLength(1));
    expect(peticiones[0]).toMatchObject({ method: "PUT", body: { keyword: "SAP", plazo_min_dias: 15 } });
  });

  it("«Probar regla» también valida antes de preguntar", async () => {
    const dialogo = await abrirEdicion();
    // `type="number"`: el navegador ya descarta lo que no es un número, así
    // que lo que llega al esquema y hay que parar es el signo.
    fireEvent.change(dialogo.getByLabelText("Importe mínimo"), { target: { value: "-1" } });
    fireEvent.click(dialogo.getByRole("button", { name: /Probar regla/ }));

    expect(await dialogo.findByText(/Escribe un importe en euros/)).toHaveAttribute("id", "edit-wl-importe-error");
    expect(peticiones).toEqual([]);
  });
});
