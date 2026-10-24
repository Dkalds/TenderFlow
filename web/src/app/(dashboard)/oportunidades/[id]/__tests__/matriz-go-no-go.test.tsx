/**
 * Matriz go/no-go de la ficha (C6.4, CU-06).
 *
 * Lo que se fija: el total, el umbral y la recomendación son los del servidor
 * y van siempre con el recuento de criterios sobre el que se calcularon; una
 * decisión que contradice la recomendación se avisa y una que no, no; puntuar
 * manda un PUT por criterio a la organización activa y la pantalla pasa a
 * enseñar la matriz recalculada que devuelve; y quien no puede escribir lee sin
 * que se le ofrezca puntuar.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import type { Pursuit } from "@/hooks/use-pursuits";
import type { PuntuacionGoNoGo } from "@/hooks/use-pursuit-go-no-go";

const h = vi.hoisted(() => ({ puedeEscribir: true, toastSuccess: vi.fn(), toastError: vi.fn() }));

vi.mock("sonner", () => ({ toast: { success: h.toastSuccess, error: h.toastError } }));
vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  organizacionResuelta: (id: unknown) => id !== undefined,
  usePuedeEscribir: () => h.puedeEscribir,
}));

import { MatrizGoNoGo } from "../_components/matriz-go-no-go";

const PURSUIT = { id: 9 } as Pursuit;

function criterios(
  puntuaciones: Partial<Record<string, [number, string | null]>>,
): PuntuacionGoNoGo["criterios"] {
  const todos: [string, string, boolean][] = [
    ["encaje", "Encaje estratégico", false],
    ["capacidad", "Capacidad de ejecución", false],
    ["competencia", "Posición frente a la competencia", false],
    ["rentabilidad", "Rentabilidad esperada", false],
    ["riesgo", "Riesgo (5 = riesgo bajo)", true],
  ];
  return todos.map(([criterio, etiqueta, invertido]) => {
    const dada = puntuaciones[criterio];
    return {
      criterio,
      etiqueta,
      invertido,
      puntuacion: dada ? dada[0] : null,
      motivo: dada ? dada[1] : null,
      author_name: dada ? "Ana Soria" : null,
    };
  });
}

function matriz(extra: Partial<PuntuacionGoNoGo> = {}): PuntuacionGoNoGo {
  return {
    pursuit_id: 9,
    organization_id: 7,
    criterios: criterios({
      encaje: [4, "Encaja con la práctica de ERP"],
      capacidad: [2, null],
      competencia: [3, null],
    }),
    total: 3,
    umbral: 3,
    recomendacion: "go",
    criterios_puntuados: 3,
    completa: false,
    decision: "pending",
    discrepa: false,
    ...extra,
  };
}

function stubApi(respuesta: PuntuacionGoNoGo, tras?: PuntuacionGoNoGo) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const llamada = [input, init] as const;
    if (callUrl(llamada).startsWith("/api/v1/pursuits/9/go-no-go")) {
      return jsonResponse(callMethod(llamada) === "PUT" && tras ? tras : respuesta);
    }
    return jsonResponse({ detail: "no esperada" }, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function pintar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MatrizGoNoGo pursuit={PURSUIT} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  h.puedeEscribir = true;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  h.toastSuccess.mockReset();
  h.toastError.mockReset();
});

describe("MatrizGoNoGo", () => {
  it("enseña el total, el umbral y la recomendación del servidor, sobre cuántos criterios", async () => {
    const fetch = stubApi(matriz({ total: 3.33, recomendacion: "go" }));
    pintar();

    expect(await screen.findByLabelText("Puntuación total")).toHaveTextContent("3,33");
    expect(screen.getByText("Recomienda GO")).toBeInTheDocument();
    expect(screen.getByText("Umbral para el GO: 3,0")).toBeInTheDocument();
    expect(screen.getByText("3 de 5 puntuados")).toBeInTheDocument();
    expect(screen.getByText(/Provisional: calculada solo sobre 3 de 5 criterios/)).toBeInTheDocument();
    // Los criterios y sus etiquetas salen de la respuesta.
    expect(screen.getByText("Riesgo (5 = riesgo bajo)")).toBeInTheDocument();
    expect(callUrl(fetch.mock.calls[0])).toBe("/api/v1/pursuits/9/go-no-go?organization_id=7");
  });

  it("con los cinco criterios dice que está completa, sin avisar de provisional", async () => {
    stubApi(
      matriz({
        criterios: criterios({
          encaje: [4, null],
          capacidad: [4, null],
          competencia: [3, null],
          rentabilidad: [4, null],
          riesgo: [5, null],
        }),
        total: 4,
        criterios_puntuados: 5,
        completa: true,
      }),
    );
    pintar();

    expect(await screen.findByText("Calculada sobre los 5 criterios.")).toBeInTheDocument();
    expect(screen.queryByText(/Provisional/)).not.toBeInTheDocument();
  });

  it("sin ningún criterio puntuado no enseña un total inventado", async () => {
    stubApi(
      matriz({
        criterios: criterios({}),
        total: 0,
        recomendacion: "sin_datos",
        criterios_puntuados: 0,
      }),
    );
    pintar();

    expect(await screen.findByLabelText("Puntuación total")).toHaveTextContent("—");
    expect(screen.getByText("Sin criterios puntuados")).toBeInTheDocument();
    expect(screen.getByText("Puntúa al menos un criterio para obtener una recomendación.")).toBeInTheDocument();
  });

  it("avisa cuando la decisión tomada discrepa de la recomendación", async () => {
    stubApi(matriz({ total: 2.2, recomendacion: "no_go", decision: "go", discrepa: true }));
    pintar();

    const aviso = await screen.findByText("La decisión GO contradice la matriz");
    expect(aviso).toBeInTheDocument();
    expect(screen.getByText(/La matriz recomienda NO-GO/)).toBeInTheDocument();
  });

  it("no avisa cuando la decisión coincide o todavía no hay", async () => {
    stubApi(matriz({ decision: "go", discrepa: false }));
    pintar();

    await screen.findByLabelText("Puntuación total");
    expect(screen.queryByText(/contradice la matriz/)).not.toBeInTheDocument();
  });

  it("puntuar un criterio con su motivo manda el PUT y pasa a la matriz recalculada", async () => {
    const recalculada = matriz({
      criterios: criterios({
        encaje: [4, "Encaja con la práctica de ERP"],
        capacidad: [2, null],
        competencia: [3, null],
        rentabilidad: [5, "Margen alto"],
      }),
      total: 3.5,
      criterios_puntuados: 4,
    });
    const fetch = stubApi(matriz(), recalculada);
    pintar();
    await screen.findByLabelText("Puntuación total");

    // Sin cambios no se ofrece guardar.
    expect(screen.queryByRole("button", { name: /^Guardar/ })).not.toBeInTheDocument();

    const grupo = screen.getByRole("group", { name: "Puntuación de «Rentabilidad esperada»" });
    fireEvent.click(within(grupo).getByRole("button", { name: "5" }));
    fireEvent.change(screen.getByLabelText("Motivo de «Rentabilidad esperada»"), {
      target: { value: "Margen alto" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar «Rentabilidad esperada»" }));

    await waitFor(() => expect(screen.getByLabelText("Puntuación total")).toHaveTextContent("3,50"));
    const put = fetch.mock.calls.find((llamada) => callMethod(llamada) === "PUT");
    expect(put).toBeDefined();
    expect(callUrl(put!)).toBe("/api/v1/pursuits/9/go-no-go?organization_id=7");
    expect(JSON.parse(String(put![1]?.body))).toEqual({
      criterio: "rentabilidad",
      puntuacion: 5,
      motivo: "Margen alto",
    });
    expect(screen.getByText("4 de 5 puntuados")).toBeInTheDocument();
    expect(h.toastSuccess).toHaveBeenCalledWith("Puntuación guardada");
    // Ya no hay nada sin guardar.
    expect(screen.queryByRole("button", { name: /^Guardar/ })).not.toBeInTheDocument();
  });

  it("no deja guardar un motivo sin puntuación", async () => {
    stubApi(matriz());
    pintar();
    await screen.findByLabelText("Puntuación total");

    fireEvent.change(screen.getByLabelText("Motivo de «Riesgo (5 = riesgo bajo)»"), {
      target: { value: "Plazo muy justo" },
    });

    expect(screen.getByRole("button", { name: "Guardar «Riesgo (5 = riesgo bajo)»" })).toBeDisabled();
  });

  it("quien no puede escribir lee las puntuaciones sin controles", async () => {
    h.puedeEscribir = false;
    stubApi(matriz());
    pintar();

    expect(await screen.findByText("4 de 5")).toBeInTheDocument();
    expect(screen.getByText("Encaja con la práctica de ERP")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Puntuación de/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Motivo de/)).not.toBeInTheDocument();
  });

  it("enlaza a Equipo → Organización, donde se cambian los pesos", async () => {
    stubApi(matriz());
    pintar();

    const enlace = await screen.findByRole("link", { name: "Pesos de los criterios" });
    expect(enlace).toHaveAttribute("href", "/equipo?tab=organizacion");
  });
});
