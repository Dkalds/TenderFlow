/**
 * Rastro de auditoría de la organización en Equipo → Actividad (CU-32).
 *
 * Lo que se fija: la tabla nombra el evento y al actor por la lista de
 * miembros (y no inventa nombre para quien ya no está); pagina con el cursor
 * opaco de la API; las fechas viajan como `desde`/`hasta` y un rango al revés
 * no llega a pedirse; el CSV lo genera la API sobre el mismo rango, y llegar
 * al tope de filas se avisa; vacío y fallo se distinguen.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import type { Schemas } from "@/lib/api-types";

import { filasDeCsv } from "../../_hooks/use-auditoria-organizacion";
import { AuditoriaOrganizacionCard } from "../auditoria-organizacion-card";

const { toastSuccess, toastError, toastWarning, descargarBlob } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastWarning: vi.fn(),
  descargarBlob: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError, warning: toastWarning } }));
vi.mock("@/lib/export", () => ({ descargarBlob }));

type Entrada = Schemas["AuditEntryOut"];

const entrada = (id: number, event_type: string, actor: number | null, over: Partial<Entrada> = {}): Entrada => ({
  id,
  ts: `2026-10-2${id}T10:00:00+00:00`,
  event_type,
  actor_user_id: actor,
  outcome: "success",
  resource: "org:7",
  detail: `user_id=${actor ?? ""}`,
  ...over,
});

const PAGINA_1 = {
  items: [entrada(3, "go_no_go.weights_updated", 1), entrada(2, "org.member_added", 99)],
  next_cursor: "c2",
  has_more: true,
  limit: 50,
};
const PAGINA_2 = {
  items: [entrada(1, "evento.desconocido", null, { outcome: "failure" })],
  next_cursor: null,
  has_more: false,
  limit: 50,
};
const MIEMBROS = [{ user_id: 1, display_name: "Ana Dueña", email: "ana@example.com", role: "owner", status: "active" }];

let csv = "id,ts,event_type\n1,2026-10-21,org.created\n";

function stubApi(rastro?: (url: string) => Response) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = callUrl([input, init]);
    if (url.startsWith("/api/v1/organizations/7/members")) return jsonResponse(MIEMBROS);
    if (url.startsWith("/api/v1/organizations/7/audit")) {
      if (rastro) return rastro(url);
      if (url.includes("formato=csv")) {
        return new Response(csv, { status: 200, headers: { "Content-Type": "text/csv" } });
      }
      return jsonResponse(url.includes("cursor=c2") ? PAGINA_2 : PAGINA_1);
    }
    return jsonResponse({ detail: "no esperada" }, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const urls = (fetch: ReturnType<typeof stubApi>) =>
  fetch.mock.calls.map((c) => callUrl(c)).filter((url) => url.includes("/audit"));

function pintar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuditoriaOrganizacionCard organizationId={7} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  csv = "id,ts,event_type\n1,2026-10-21,org.created\n";
});

afterEach(() => {
  vi.unstubAllGlobals();
  for (const fn of [toastSuccess, toastError, toastWarning, descargarBlob]) fn.mockReset();
});

describe("AuditoriaOrganizacionCard", () => {
  it("nombra cada evento y a su actor, y pagina con el cursor de la API", async () => {
    const fetch = stubApi();
    pintar();

    const tabla = await screen.findByRole("table", { name: "Rastro de auditoría de la organización" });
    const pesos = within(tabla).getByRole("row", { name: /Cambió los pesos del go\/no-go/ });
    await waitFor(() => expect(pesos).toHaveTextContent("Ana Dueña"));
    // Quien ya no es miembro se queda con su id.
    expect(within(tabla).getByRole("row", { name: /Añadió un miembro/ })).toHaveTextContent("Usuario #99");

    fireEvent.click(screen.getByRole("button", { name: "Cargar más" }));
    const ultima = await within(tabla).findByRole("row", { name: /evento\.desconocido/ });
    expect(ultima).toHaveTextContent("Sistema");
    expect(ultima).toHaveTextContent("No se completó");
    expect(screen.getByText("No hay eventos anteriores en este rango.")).toBeInTheDocument();
    expect(urls(fetch)).toEqual([
      "/api/v1/organizations/7/audit?limit=50",
      "/api/v1/organizations/7/audit?limit=50&cursor=c2",
    ]);
  });

  it("las fechas acotan la consulta, y un rango al revés no se pide", async () => {
    const fetch = stubApi();
    pintar();
    await screen.findByRole("table");

    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2026-10-01" } });
    await waitFor(() =>
      expect(urls(fetch)).toContain("/api/v1/organizations/7/audit?desde=2026-10-01&limit=50"),
    );

    const antes = urls(fetch).length;
    fireEvent.change(screen.getByLabelText("Hasta"), { target: { value: "2026-09-01" } });
    expect(await screen.findByText("Es anterior a «Desde».")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Descargar CSV/ })).toBeDisabled();
    expect(urls(fetch)).toHaveLength(antes);
  });

  it("descarga el CSV que genera la API para el mismo rango", async () => {
    const fetch = stubApi();
    pintar();
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("Hasta"), { target: { value: "2026-10-22" } });

    fireEvent.click(screen.getByRole("button", { name: /Descargar CSV/ }));
    await waitFor(() => expect(descargarBlob).toHaveBeenCalled());
    expect(urls(fetch)).toContain("/api/v1/organizations/7/audit?hasta=2026-10-22&formato=csv&limit=500");
    expect(descargarBlob.mock.calls[0][0]).toBe("auditoria-organizacion-7.csv");
    expect(descargarBlob.mock.calls[0][2]).toBe("auditoria-organizacion");
    expect(toastSuccess).toHaveBeenCalledWith("CSV descargado: 1 eventos.");
  });

  it("un CSV que llega al tope de filas lo avisa para que se acote por fechas", async () => {
    csv = "id\n" + Array.from({ length: 500 }, (_, i) => `${i}\n`).join("");
    stubApi();
    pintar();
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: /Descargar CSV/ }));
    await waitFor(() => expect(toastWarning).toHaveBeenCalled());
    expect(toastWarning.mock.calls[0][0]).toMatch(/500 eventos más recientes del rango/);
  });

  it("sin eventos lo dice; si la API lo niega, lo enseña con reintentar", async () => {
    stubApi(() => jsonResponse({ items: [], next_cursor: null, has_more: false, limit: 50 }));
    const { unmount } = pintar();
    expect(await screen.findByText("Todavía no hay nada registrado")).toBeInTheDocument();
    unmount();

    stubApi(() => jsonResponse({ detail: "Solo owner o admin pueden leer el rastro." }, 403));
    pintar();
    const aviso = await screen.findByRole("alert");
    expect(within(aviso).getByText("No se pudo cargar el rastro de auditoría")).toBeInTheDocument();
    expect(within(aviso).getByRole("button", { name: /Reintentar/ })).toBeInTheDocument();
  });
});

describe("filasDeCsv", () => {
  it("cuenta registros sin la cabecera y sin partir celdas con saltos de línea", () => {
    expect(filasDeCsv("a,b\n1,2\n3,4\n")).toBe(2);
    expect(filasDeCsv('a,b\n1,"línea uno\nlínea dos"\n')).toBe(1);
    expect(filasDeCsv("a,b\n")).toBe(0);
    expect(filasDeCsv("")).toBe(0);
  });
});
