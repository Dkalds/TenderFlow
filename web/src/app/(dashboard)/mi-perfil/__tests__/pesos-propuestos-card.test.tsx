import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * S3.3 — la propuesta de pesos se enseña con su base y no se aplica sola.
 *
 * Las tres reglas que fija este suite son las del plan, y todas son de
 * producto: con menos de `minimo_cierres` no hay propuesta pero **sí** hay
 * tarjeta diciendo cuánto falta; la propuesta viaja con cuántas ganadas y
 * cuántas perdidas la sostienen; y aplicarla exige un clic explícito más su
 * confirmación, sin mandar pesos en el cuerpo (los recalcula el backend).
 */

// `vi.hoisted` y no dos `const` sueltos: la factoría de `vi.mock` se iza al
// principio del fichero y leería los dobles antes de que existan.
const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

const apiGet = vi.hoisted(() => vi.fn());
const apiMutate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", () => ({ apiGet, apiMutate }));

vi.mock("@/hooks/use-organization", () => ({ useActiveOrganizationId: () => 7 }));

import { PesosPropuestosCard } from "@/app/(dashboard)/mi-perfil/_components/pesos-propuestos-card";

const INSUFICIENTE = {
  estado: "insuficiente",
  n_cierres: 7,
  n_ganadas: 4,
  n_perdidas: 3,
  minimo_cierres: 20,
  organization_id: 7,
  origen_pesos_actuales: "global",
  pesos_actuales: {},
  dimensiones: [],
  pesos_propuestos: null,
};

const PROPUESTA = {
  estado: "propuesta",
  n_cierres: 24,
  n_ganadas: 14,
  n_perdidas: 10,
  minimo_cierres: 20,
  organization_id: 7,
  origen_pesos_actuales: "perfil",
  pesos_actuales: { importe: 20, afinidad: 15 },
  pesos_propuestos: { importe: 24, afinidad: 11 },
  dimensiones: [
    {
      dimension: "importe",
      peso_actual: 20,
      peso_propuesto: 24,
      media_ganadas: 71,
      media_perdidas: 52,
      delta: 19,
    },
    {
      dimension: "afinidad",
      peso_actual: 15,
      peso_propuesto: 11,
      media_ganadas: 44,
      media_perdidas: 58,
      delta: -14,
    },
  ],
};

function renderCard(propuesta: unknown = PROPUESTA) {
  apiGet.mockResolvedValue(propuesta);
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <PesosPropuestosCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiGet.mockReset();
  apiMutate.mockReset();
  apiMutate.mockResolvedValue({ pesos: {}, n_cierres: 24, organization_id: 7, visibility: "private" });
  toastSuccess.mockClear();
  toastError.mockClear();
});

afterEach(() => {
  cleanup();
});

describe("pesos propuestos en /mi-perfil", () => {
  it("con pocos cierres dice cuántos faltan en vez de esconderse", async () => {
    renderCard(INSUFICIENTE);

    expect(await screen.findByText(/llevas/)).toHaveTextContent(
      /llevas\s*7\s*de 20 cierres con desglose sellado, así que faltan\s*13/,
    );
    // Y no se ofrece aplicar nada: no hay propuesta que aplicar.
    expect(screen.queryByRole("button", { name: /Aplicar la propuesta/ })).not.toBeInTheDocument();
  });

  it("enseña la propuesta con su base y el salto por dimensión", async () => {
    renderCard();

    expect(await screen.findByText(/24 cierres con desglose sellado/)).toBeInTheDocument();
    expect(screen.getByText(/14 ganadas y 10 perdidas/)).toBeInTheDocument();
    expect(screen.getByText("Importe")).toBeInTheDocument();
    expect(screen.getByText("24")).toBeInTheDocument();
    expect(
      screen.getByText(/Media en ganadas 71 · en perdidas 52 \(diferencia 19\)/),
    ).toBeInTheDocument();
  });

  it("aplicar exige confirmación y no manda pesos en el cuerpo", async () => {
    renderCard();

    fireEvent.click(await screen.findByRole("button", { name: "Aplicar la propuesta" }));
    // El primer clic no escribe: pide confirmación.
    expect(apiMutate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "¿Aplicar estos pesos a tu perfil?" }));

    await waitFor(() => expect(apiMutate).toHaveBeenCalled());
    expect(apiMutate).toHaveBeenCalledWith(
      "POST",
      "/api/v1/pursuits/weights-proposal/apply?organization_id=7",
    );
    // Dos argumentos: el cuerpo no existe. Los pesos los recalcula el backend.
    expect(apiMutate.mock.calls[0]).toHaveLength(2);
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
  });

  it("cancelar la confirmación no escribe nada", async () => {
    renderCard();

    fireEvent.click(await screen.findByRole("button", { name: "Aplicar la propuesta" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(apiMutate).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Aplicar la propuesta" })).toBeInTheDocument();
  });

  it("un fallo al aplicar se dice y no se cuenta como aplicado", async () => {
    apiMutate.mockRejectedValue(new Error("403"));
    renderCard();

    fireEvent.click(await screen.findByRole("button", { name: "Aplicar la propuesta" }));
    fireEvent.click(screen.getByRole("button", { name: "¿Aplicar estos pesos a tu perfil?" }));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("403"));
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("si el backend no contesta, la tarjeta no inventa una propuesta", async () => {
    apiGet.mockRejectedValue(new Error("500"));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(
      <QueryClientProvider client={qc}>
        <PesosPropuestosCard />
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/No se pudo calcular la propuesta de pesos/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Aplicar/ })).not.toBeInTheDocument();
  });
});
