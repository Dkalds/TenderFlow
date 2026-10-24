/**
 * Pesos de la matriz go/no-go en Equipo → Organización (C6.4, CU-06).
 *
 * Lo que se fija: los criterios, sus etiquetas y el umbral salen de la
 * respuesta; cada peso dice qué parte del total supone con lo escrito; el PUT
 * lleva todos los pesos como número a la organización activa; un peso fuera
 * de rango se explica bajo su campo y todos a cero se para antes de la API
 * (el backend los trataría como «sin configurar»); y quien no administra lee
 * sin que se le ofrezca guardar.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import type { Schemas } from "@/lib/api-types";

import { partesDelTotal, PesosGoNoGoCard } from "../pesos-go-no-go-card";

const { toastSuccess, toastError } = vi.hoisted(() => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

const criterio = (c: string, etiqueta: string, peso: number): Schemas["GoNoGoCriterioOut"] => ({
  criterio: c,
  etiqueta,
  invertido: c === "riesgo",
  peso,
});

const PESOS: Schemas["GoNoGoWeightsOut"] = {
  organization_id: 7,
  umbral: 3,
  criterios: [
    criterio("encaje", "Encaje estratégico", 2),
    criterio("capacidad", "Capacidad de ejecución", 1),
    criterio("competencia", "Posición frente a la competencia", 1),
    criterio("rentabilidad", "Rentabilidad esperada", 0),
    criterio("riesgo", "Riesgo (5 = riesgo bajo)", 1),
  ],
};

function stubApi() {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const llamada = [input, init] as const;
    const url = callUrl(llamada);
    if (url.startsWith("/api/v1/organizations/go-no-go/weights")) {
      if (callMethod(llamada) === "PUT") {
        const { pesos } = JSON.parse(String(init?.body)) as { pesos: Record<string, number> };
        return jsonResponse({
          ...PESOS,
          criterios: PESOS.criterios.map((c) => ({ ...c, peso: pesos[c.criterio] ?? c.peso })),
        });
      }
      return jsonResponse(PESOS);
    }
    return jsonResponse({ detail: "no esperada" }, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function pintar(canManage: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PesosGoNoGoCard organizationId={7} canManage={canManage} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  toastSuccess.mockReset();
  toastError.mockReset();
});

describe("PesosGoNoGoCard", () => {
  it("pinta los criterios del backend con su peso, su parte del total y el umbral", async () => {
    const fetch = stubApi();
    pintar(true);

    const encaje = await screen.findByLabelText("Encaje estratégico");
    expect(encaje).toHaveValue("2");
    expect(screen.getByLabelText("Riesgo (5 = riesgo bajo)")).toHaveValue("1");
    // 2 de un total de 5.
    expect(screen.getByText("40% del total")).toBeInTheDocument();
    expect(screen.getByText("0% del total")).toBeInTheDocument();
    expect(screen.getByText(/media ponderada de 3,0 o más/)).toBeInTheDocument();
    expect(callUrl(fetch.mock.calls[0])).toBe("/api/v1/organizations/go-no-go/weights?organization_id=7");
  });

  it("la parte del total se recalcula con lo que se escribe", async () => {
    stubApi();
    pintar(true);
    fireEvent.change(await screen.findByLabelText("Encaje estratégico"), { target: { value: "6" } });
    // 6 de un total de 9.
    expect(await screen.findByText("67% del total")).toBeInTheDocument();
  });

  it("guarda todos los pesos como número en la organización activa", async () => {
    const fetch = stubApi();
    pintar(true);
    fireEvent.change(await screen.findByLabelText("Rentabilidad esperada"), { target: { value: "1,5" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar pesos" }));

    await waitFor(() => expect(fetch.mock.calls.some((c) => callMethod(c) === "PUT")).toBe(true));
    const put = fetch.mock.calls.find((c) => callMethod(c) === "PUT")!;
    expect(callUrl(put)).toBe("/api/v1/organizations/go-no-go/weights?organization_id=7");
    expect(JSON.parse(String((put[1] as RequestInit).body))).toEqual({
      pesos: { encaje: 2, capacidad: 1, competencia: 1, rentabilidad: 1.5, riesgo: 1 },
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
  });

  it("un peso fuera de rango se explica bajo su campo y no llama a la API", async () => {
    const fetch = stubApi();
    pintar(true);
    const campo = await screen.findByLabelText("Capacidad de ejecución");
    fireEvent.change(campo, { target: { value: "-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar pesos" }));

    expect(await screen.findByText("Escribe un peso entre 0 y 100.")).toBeInTheDocument();
    expect(campo).toHaveAttribute("aria-invalid", "true");
    expect(fetch.mock.calls.some((c) => callMethod(c) === "PUT")).toBe(false);
  });

  it("todos a cero no se guarda: el backend volvería en silencio a los pesos iguales", async () => {
    const fetch = stubApi();
    pintar(true);
    await screen.findByLabelText("Encaje estratégico");
    for (const etiqueta of ["Encaje estratégico", "Capacidad de ejecución", "Posición frente a la competencia", "Riesgo (5 = riesgo bajo)"]) {
      fireEvent.change(screen.getByLabelText(etiqueta), { target: { value: "0" } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Guardar pesos" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Al menos un criterio tiene que pesar algo/);
    expect(fetch.mock.calls.some((c) => callMethod(c) === "PUT")).toBe(false);
  });

  it("sin permiso se lee pero no se ofrece guardar", async () => {
    stubApi();
    pintar(false);
    expect(await screen.findByLabelText("Encaje estratégico")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Guardar/ })).not.toBeInTheDocument();
    expect(screen.getByText("Solo un propietario o un administrador puede cambiarlos.")).toBeInTheDocument();
  });

  it("si la API falla, lo dice y ofrece reintentar", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "No sos miembro de esa organización." }, 403)),
    );
    pintar(true);
    const aviso = await screen.findByRole("alert");
    expect(within(aviso).getByText("No se pudieron cargar los pesos del go/no-go")).toBeInTheDocument();
    expect(within(aviso).getByRole("button", { name: /Reintentar/ })).toBeInTheDocument();
  });
});

describe("partesDelTotal", () => {
  it("reparte sobre lo que es un número válido y calla lo demás", () => {
    expect(partesDelTotal({ a: "1", b: "3", c: "" , d: "x" })).toEqual({ a: 25, b: 75, c: null, d: null });
    expect(partesDelTotal({ a: "0", b: "0" })).toEqual({ a: null, b: null });
  });
});
