import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * T6 — la tarjeta que enciende el informe semanal.
 *
 * Lo que se fija aquí es de producto, no de maquetación:
 *
 * 1. **Vacío significa «owner y admin»**, y por tanto se manda `null` y no
 *    `[]`. Si la tarjeta mandara una lista vacía, el backend la guardaría como
 *    lista explícita de cero personas y el informe dejaría de salir sin que
 *    nadie hubiera pedido apagarlo.
 * 2. **0 = lunes**, la numeración del backend, no la de `Date.getDay()`.
 * 3. **Quien no es owner ni admin no ve la tarjeta y no pide los datos**: el
 *    backend le responde 403, así que la petición sobra.
 * 4. Un correo mal escrito se para aquí nombrando la línea, en vez de viajar y
 *    volver como un 422 opaco.
 */

const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

const fetchWithAuth = vi.hoisted(() => vi.fn());
const apiMutate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", () => ({ fetchWithAuth, apiMutate, apiGet: vi.fn() }));

const rol = vi.hoisted(() => ({ actual: "owner" as string }));
vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  useOrganizations: () => ({ data: [{ id: 7, role: rol.actual }] }),
}));

import {
  InformeSemanalCard,
  proximaEntrega,
} from "@/app/(dashboard)/mi-perfil/_components/informe-semanal-card";

const PROGRAMACION = {
  organization_id: 7,
  tipo: "pipeline_semanal",
  activo: false,
  dia_semana: 0,
  hora_utc: 7,
  destinatarios: null,
  ultimo_envio_at: null,
  ultimo_estado: null,
};

function renderCard(programacion: unknown = PROGRAMACION) {
  fetchWithAuth.mockResolvedValue(programacion);
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <InformeSemanalCard />
    </QueryClientProvider>,
  );
}

/** El `<span>` visible del trigger; Radix pinta además un `<option>` oculto. */
const trigger = (texto: string) => screen.getByText(texto, { selector: "span" });

beforeEach(() => {
  rol.actual = "owner";
  apiMutate.mockResolvedValue({ ...PROGRAMACION, activo: true });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("proximaEntrega", () => {
  // Se comprueba en UTC a propósito: el resultado no puede depender de la zona
  // horaria en que corra el runner.
  it("avanza hasta el próximo día programado", () => {
    // 2026-09-15 es martes. Pedir el jueves (índice 3) debe dar el 17.
    const desde = new Date("2026-09-15T10:00:00Z");
    const cuando = proximaEntrega(3, 7, desde);
    expect(cuando.toISOString()).toBe("2026-09-17T07:00:00.000Z");
  });

  it("salta a la semana siguiente cuando la hora de hoy ya pasó", () => {
    // Martes a las 10:00 UTC, programado los martes a las 07:00: ya pasó.
    const desde = new Date("2026-09-15T10:00:00Z");
    expect(proximaEntrega(1, 7, desde).toISOString()).toBe("2026-09-22T07:00:00.000Z");
  });

  it("trata 0 como lunes y no como domingo", () => {
    const desde = new Date("2026-09-15T10:00:00Z"); // martes
    const cuando = proximaEntrega(0, 7, desde);
    expect(cuando.toISOString()).toBe("2026-09-21T07:00:00.000Z"); // lunes siguiente
    expect(cuando.getUTCDay()).toBe(1); // 1 = lunes en `getUTCDay`
  });
});

describe("InformeSemanalCard", () => {
  it("enseña la programación guardada y no deja guardar sin cambios", async () => {
    renderCard();

    expect(await screen.findByRole("switch")).toBeInTheDocument();
    expect(trigger("lunes")).toBeInTheDocument();
    expect(trigger("07:00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Guardar programación/ })).toBeDisabled();
  });

  it("manda destinatarios null cuando la caja está vacía", async () => {
    renderCard();

    fireEvent.click(await screen.findByRole("switch"));
    const guardar = screen.getByRole("button", { name: /Guardar programación/ });
    await waitFor(() => expect(guardar).not.toBeDisabled());
    fireEvent.click(guardar);

    await waitFor(() => expect(apiMutate).toHaveBeenCalledTimes(1));
    expect(apiMutate).toHaveBeenCalledWith(
      "PUT",
      "/api/v1/organizations/7/report-schedule",
      { activo: true, dia_semana: 0, hora_utc: 7, destinatarios: null },
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
  });

  it("parte la lista por líneas y la manda tal cual", async () => {
    renderCard();

    const caja = await screen.findByLabelText("Destinatarios");
    fireEvent.change(caja, {
      target: { value: "direccion@example.test\n  comite@example.test  \n\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Guardar programación/ }));

    await waitFor(() => expect(apiMutate).toHaveBeenCalledTimes(1));
    expect(apiMutate.mock.calls[0][2]).toMatchObject({
      destinatarios: ["direccion@example.test", "comite@example.test"],
    });
  });

  it("para un correo mal escrito nombrándolo, sin llamar al backend", async () => {
    renderCard();

    const caja = await screen.findByLabelText("Destinatarios");
    fireEvent.change(caja, { target: { value: "direccion@example.test\nno-es-un-correo" } });
    fireEvent.click(screen.getByRole("button", { name: /Guardar programación/ }));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(String(toastError.mock.calls[0][0])).toContain("no-es-un-correo");
    expect(apiMutate).not.toHaveBeenCalled();
  });

  it("explica el último envío en vez de enseñar el código crudo", async () => {
    renderCard({
      ...PROGRAMACION,
      activo: true,
      ultimo_envio_at: "2026-09-14T07:12:00Z",
      ultimo_estado: "enviado:2/3",
    });

    expect(await screen.findByText(/Enviado a 2 de 3/)).toBeInTheDocument();
  });

  it("no se pinta ni pide nada para quien no es owner ni admin", async () => {
    rol.actual = "member";
    const { container } = renderCard();

    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(fetchWithAuth).not.toHaveBeenCalled();
  });
});
