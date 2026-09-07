/**
 * Cola de revisión: la ventana de deshacer y la única alarma por fila.
 *
 * Lo que fijan estos tests es la decisión de diseño que hace posible el
 * «Deshacer» sin endpoint inverso: la escritura no sale hasta que se cierra la
 * ventana, así que deshacer no revierte nada — cancela.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ReviewQueue } from "../_components/review-queue";
import { nifEnConflicto, UNDO_MS, useReviewQueue, type ReviewItem } from "../_hooks/use-review-queue";

const { apiMutate, fetchWithAuth } = vi.hoisted(() => ({
  apiMutate: vi.fn().mockResolvedValue({}),
  fetchWithAuth: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({
  apiMutate,
  fetchWithAuth,
  ApiError: class ApiError extends Error {},
}));

const ITEMS: ReviewItem[] = [
  {
    id: 1,
    nombre_original: "INDRA SISTEMAS S.A",
    nif: "A28599033",
    score: 0.97,
    candidato_empresa_id: 10,
    candidato_nombre: "Indra Sistemas, S.A.",
    candidato_nif: "A28599033",
  },
  {
    id: 3,
    nombre_original: "AYESA ADVANCED TECHNOLOGIES SA",
    nif: "B41002205",
    score: 0.91,
    candidato_empresa_id: 12,
    candidato_nombre: "Ayesa Advanced Technologies",
    candidato_nif: "A41002205",
  },
  {
    id: 7,
    nombre_original: "BABEL SISTEMAS DE INFORMACION SL",
    nif: null,
    score: 0.79,
    candidato_empresa_id: 14,
    candidato_nombre: "Babel Sistemas de Información",
    candidato_nif: "A82292988",
  },
];

function Wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // Los mismos proveedores que monta `components/providers.tsx` en la app.
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>
  );
}

/** Monta el hook dentro de un componente que pinta la cola de verdad. */
function ColaEnVivo() {
  const cola = useReviewQueue({ enabled: true });
  return (
    <ReviewQueue
      items={cola.items}
      loading={cola.isLoading}
      error={cola.isError}
      onRetry={() => {}}
      filtro="all"
      onFiltroChange={() => {}}
      onDecidir={(ids, accept) => cola.decidir(ids, accept)}
    />
  );
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  apiMutate.mockClear();
  fetchWithAuth.mockResolvedValue({ items: ITEMS });
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("nifEnConflicto", () => {
  it("marca sólo la fila cuyos dos NIF se contradicen", () => {
    // Es la única alarma de la fila: la similitud pasó a barra neutra porque
    // tener semáforo de score *y* NIF en rojo era juzgar lo mismo dos veces.
    expect(nifEnConflicto(ITEMS[0])).toBe(false);
    expect(nifEnConflicto(ITEMS[1])).toBe(true);
  });

  it("no llama conflicto a un NIF que la fuente no trae", () => {
    // Sin NIF en origen no hay contradicción, hay ausencia.
    expect(nifEnConflicto(ITEMS[2])).toBe(false);
  });
});

describe("cola de revisión", () => {
  it("pinta «Unir» y «Nueva» con texto, no con iconos sueltos", async () => {
    // En una cola donde cada clic reescribe el maestro, saber qué hace el
    // botón no puede depender de dejar el ratón quieto encima.
    render(<ColaEnVivo />, { wrapper: Wrapper });
    await screen.findAllByRole("button", { name: "Unir" });
    expect(screen.getAllByRole("button", { name: "Unir" })).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: "Nueva" })).toHaveLength(3);
  });

  it("saca la fila al decidir, pero no escribe hasta cerrar la ventana", async () => {
    render(<ColaEnVivo />, { wrapper: Wrapper });
    const unir = await screen.findAllByRole("button", { name: "Unir" });

    fireEvent.click(unir[0]);

    // La cola responde al instante…
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Unir" })).toHaveLength(2));
    // …y la escritura todavía no ha salido: eso es lo que hace real el
    // «Deshacer» del toast, que no tiene endpoint inverso al que llamar.
    expect(apiMutate).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(UNDO_MS + 10);
    expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/empresas/reviews/1", {
      accept: true,
    });
  });

  it("«Unir los ≥ 90 %» pide confirmación antes de tocar el lote", async () => {
    render(<ColaEnVivo />, { wrapper: Wrapper });
    const boton = await screen.findByRole("button", { name: /Unir los ≥ 90 %/ });
    // Dos de los tres matches pasan del umbral.
    expect(boton).toHaveTextContent("(2)");

    fireEvent.click(boton);
    expect(apiMutate).not.toHaveBeenCalled();
    expect(screen.getByText(/Se recalculan importe resuelto y cuotas/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Unir todos" }));
    await vi.advanceTimersByTimeAsync(UNDO_MS + 10);
    expect(apiMutate).toHaveBeenCalledTimes(2);
  });

  it("cancelar el lote no decide nada", async () => {
    render(<ColaEnVivo />, { wrapper: Wrapper });
    fireEvent.click(await screen.findByRole("button", { name: /Unir los ≥ 90 %/ }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    await vi.advanceTimersByTimeAsync(UNDO_MS + 10);
    expect(apiMutate).not.toHaveBeenCalled();
    expect(screen.getAllByRole("button", { name: "Unir" })).toHaveLength(3);
  });

  it("el filtro de confianza recorta la lista sin decidir por nadie", async () => {
    const { rerender } = render(
      <ReviewQueue
        items={ITEMS}
        loading={false}
        error={false}
        onRetry={() => {}}
        filtro="all"
        onFiltroChange={() => {}}
        onDecidir={() => {}}
      />,
      { wrapper: Wrapper },
    );
    expect(screen.getAllByRole("button", { name: "Unir" })).toHaveLength(3);

    rerender(
      <ReviewQueue
        items={ITEMS}
        loading={false}
        error={false}
        onRetry={() => {}}
        filtro="doubt"
        onFiltroChange={() => {}}
        onDecidir={() => {}}
      />,
    );
    expect(screen.getAllByRole("button", { name: "Unir" })).toHaveLength(1);
    expect(screen.getByText(/1 de 3 matches dudosos/)).toBeInTheDocument();
  });

  it("un filtro sin resultados distingue «cola vacía» de «nada en este filtro»", () => {
    render(
      <ReviewQueue
        items={ITEMS}
        loading={false}
        error={false}
        onRetry={() => {}}
        filtro="safe"
        onFiltroChange={() => {}}
        onDecidir={() => {}}
      />,
      { wrapper: Wrapper },
    );
    expect(screen.queryByText("Cola vacía")).not.toBeInTheDocument();

    cleanup();
    render(
      <ReviewQueue
        items={[]}
        loading={false}
        error={false}
        onRetry={() => {}}
        filtro="all"
        onFiltroChange={() => {}}
        onDecidir={() => {}}
      />,
      { wrapper: Wrapper },
    );
    expect(screen.getByText("Cola vacía")).toBeInTheDocument();
  });

  it("el error de la cola es del bloque y ofrece reintentar", () => {
    const onRetry = vi.fn();
    render(
      <ReviewQueue
        items={[]}
        loading={false}
        error
        errorDetail="500 · /api/v1/empresas/reviews"
        onRetry={onRetry}
        filtro="all"
        onFiltroChange={() => {}}
        onDecidir={() => {}}
      />,
      { wrapper: Wrapper },
    );
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo cargar la cola de revisión");
    fireEvent.click(screen.getByRole("button", { name: /Reintentar/ }));
    expect(onRetry).toHaveBeenCalled();
  });
});
