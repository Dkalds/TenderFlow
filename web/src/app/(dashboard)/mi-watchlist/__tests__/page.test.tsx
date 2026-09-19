import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  // La página limpia `?baja=<n>` tras avisar de la baja de correos.
  useRouter: () => ({ replace: vi.fn() }),
}));

const { registrarEvento } = vi.hoisted(() => ({ registrarEvento: vi.fn() }));
vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  registrarEvento,
}));

import MiWatchlistPage from "@/app/(dashboard)/mi-watchlist/page";

const RULE = {
  id: 42,
  nombre: "SAP en Madrid",
  keyword: "SAP",
  cpv: "72000000",
  min_importe: 50000,
  ccaa: "Madrid",
  frequency: "daily" as const,
  active: true,
  match_count: 7,
  email: "user@example.com",
};

const RULE_NO_EMAIL = { ...RULE, id: 43, email: null, keyword: "Salesforce" };

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body };
}

/** Router de fetch por (method, url) -- las páginas de este repo usan fetch
 * crudo con credentials:"include" contra la API real, no el cliente OpenAPI. */
function mockFetchRouter(handlers: {
  onPut?: (id: number, body: unknown) => void;
  rules?: typeof RULE[];
}) {
  const rules = handlers.rules ?? [RULE, RULE_NO_EMAIL];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/v1/watchlist/rules" && method === "GET") {
        return jsonResponse({ items: rules });
      }
      if (url === "/api/v1/watchlist/rules" && method === "POST") {
        return jsonResponse({ id: 99 });
      }
      if (url.startsWith("/api/v1/watchlist/rules/") && url.endsWith("/matches")) {
        return jsonResponse({ items: [] });
      }
      if (url === "/api/v1/meta/filters") {
        return jsonResponse({ ccaas: ["Madrid", "Cataluna"] });
      }
      if (url === "/api/v1/watchlist/rules/preview" && method === "POST") {
        // Forma de `PreviewResult` (F5.5): ocho semanas, antiguas primero.
        return jsonResponse({
          total: 12,
          serie_semanal: [
            "2026-07-06",
            "2026-07-13",
            "2026-07-20",
            "2026-07-27",
            "2026-08-03",
            "2026-08-10",
            "2026-08-17",
            "2026-08-24",
          ].map((semana, i) => ({ semana, n: 60 + i })),
          umbral_semanal: 50,
          ruido_alto: true,
        });
      }
      if (url.match(/\/api\/v1\/watchlist\/rules\/\d+$/) && method === "PUT") {
        const id = Number(url.split("/").pop());
        const body = init?.body ? JSON.parse(init.body as string) : {};
        handlers.onPut?.(id, body);
        return jsonResponse({ status: "ok" });
      }
      return jsonResponse({}, false, 404);
    }),
  );
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  // Las acciones de regla (activar / editar / eliminar) llevan `Tooltip`, y
  // `Tooltip.Root` de Radix revienta sin un `TooltipProvider` por encima: en la
  // app lo pone `components/providers.tsx`, aquí hay que ponerlo a mano.
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <MiWatchlistPage />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("MiWatchlistPage — edición de reglas", () => {
  it("displays the delivery email on each rule card", async () => {
    mockFetchRouter({});
    renderPage();

    await waitFor(() => expect(screen.getByText("user@example.com")).toBeInTheDocument());
    expect(screen.getByText("Solo notificaciones in-app")).toBeInTheDocument();
  });

  it("opens the edit sheet pre-filled with the rule's current values", async () => {
    mockFetchRouter({});
    renderPage();

    await waitFor(() => expect(screen.getAllByRole("button", { name: "Editar regla" })[0]).toBeInTheDocument());
    fireEvent.click(screen.getAllByRole("button", { name: "Editar regla" })[0]);

    expect(await screen.findByText("Editar regla")).toBeInTheDocument();
    const dialog = within(screen.getByRole("dialog"));
    // Sin asterisco: desde S4.4 la palabra clave dejó de ser obligatoria — una
    // regla puede filtrar solo por órgano, tecnología o banda del Radar.
    const keywordInput = dialog.getByLabelText("Palabra clave") as HTMLInputElement;
    expect(keywordInput.value).toBe("SAP");
    const cpvInput = dialog.getByLabelText("Filtro CPV") as HTMLInputElement;
    expect(cpvInput.value).toBe("72000000");
    const importeInput = dialog.getByLabelText("Importe mínimo") as HTMLInputElement;
    expect(importeInput.value).toBe("50000");
    // El email de entrega también se muestra dentro del panel de edición.
    expect(dialog.getByText(/Entrega por email a/)).toBeInTheDocument();
  });

  it("saves the edited rule via PUT with the updated fields", async () => {
    const onPut = vi.fn();
    mockFetchRouter({ onPut });
    renderPage();

    await waitFor(() => expect(screen.getAllByRole("button", { name: "Editar regla" })[0]).toBeInTheDocument());
    fireEvent.click(screen.getAllByRole("button", { name: "Editar regla" })[0]);
    await screen.findByText("Editar regla");

    const dialog = within(screen.getByRole("dialog"));
    const keywordInput = dialog.getByLabelText("Palabra clave");
    fireEvent.change(keywordInput, { target: { value: "SAP S/4HANA" } });
    fireEvent.click(dialog.getByRole("button", { name: "Guardar cambios" }));

    await waitFor(() => expect(onPut).toHaveBeenCalledTimes(1));
    const [id, body] = onPut.mock.calls[0];
    expect(id).toBe(42);
    expect(body.keyword).toBe("SAP S/4HANA");
    expect(body.cpv).toBe("72000000"); // el resto de campos precargados se preserva
  });

  it('"Probar regla" shows the match count without saving', async () => {
    const onPut = vi.fn();
    mockFetchRouter({ onPut });
    renderPage();

    await waitFor(() => expect(screen.getAllByRole("button", { name: "Editar regla" })[0]).toBeInTheDocument());
    fireEvent.click(screen.getAllByRole("button", { name: "Editar regla" })[0]);
    await screen.findByText("Editar regla");

    fireEvent.click(screen.getByRole("button", { name: /Probar regla/ }));

    expect(await screen.findByText(/12 licitación\(es\) coincidirían hoy/)).toBeInTheDocument();
    // F5.5 — la serie va en una tabla para el lector y el aviso lo decide el servidor.
    const tabla = screen.getByRole("table", { name: "Coincidencias por semana" });
    expect(within(tabla).getAllByRole("row")).toHaveLength(1 + 8 + 1);
    expect(screen.getByRole("status")).toHaveTextContent(/esta regla va a hacer ruido/);
    expect(onPut).not.toHaveBeenCalled();
  });
});

describe("MiWatchlistPage — alta con vista previa de ruido (F5.5)", () => {
  it("crear tras ver el aviso manda ruido_avisado; sin vista previa no lo manda", async () => {
    mockFetchRouter({});
    renderPage();

    fireEvent.change(await screen.findByLabelText(/Palabra clave/), { target: { value: "ERP" } });
    fireEvent.click(screen.getByRole("button", { name: /Ver cuántas alertas daría/ }));
    expect(await screen.findByRole("status")).toHaveTextContent(/va a hacer ruido/);

    fireEvent.click(screen.getByRole("button", { name: /Agregar regla/ }));
    await waitFor(() =>
      expect(registrarEvento).toHaveBeenCalledWith(
        "regla_creada",
        expect.objectContaining({ ruido_avisado: "si" }),
      ),
    );

    registrarEvento.mockClear();
    fireEvent.change(screen.getByLabelText(/Palabra clave/), { target: { value: "CRM" } });
    fireEvent.click(screen.getByRole("button", { name: /Agregar regla/ }));
    await waitFor(() => expect(registrarEvento).toHaveBeenCalledWith("regla_creada", expect.anything()));
    expect(registrarEvento.mock.calls[0][1]).not.toHaveProperty("ruido_avisado");
  });
});
