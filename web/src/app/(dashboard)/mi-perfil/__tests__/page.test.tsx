import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Lo que este fichero fija es el **primer paso del embudo de activación**.
 *
 * Ajustar el perfil de scoring es lo que más pesa de los tres pasos de la banda
 * «Primeros pasos» —hasta que se hace, el Radar puntúa con los pesos genéricos
 * de `settings.SCORING_WEIGHTS` y lo que el usuario ve arriba está ordenado
 * para otro—, y sin embargo era el único de los tres que no emitía nada: el
 * embudo se medía desde el segundo escalón, así que la caída más cara era
 * justamente la invisible.
 *
 * La otra mitad de lo que se comprueba aquí es de privacidad: por este evento
 * no puede viajar el contenido del perfil. Los pesos, las keywords y los CPV de
 * alguien son su estrategia comercial, y el catálogo (`lib/analytics.ts` §1)
 * sólo admite dimensiones categóricas cerradas.
 *
 * `primeraVez` se deja **real** a propósito (sólo se dobla `registrarEvento`):
 * lo que separa activación de reajuste es su sello en `localStorage`, y
 * doblarlo devolviendo siempre "si" haría verde un test que no prueba nada.
 */

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/lib/api-client", () => ({
  fetchWithAuth: vi.fn(),
  apiMutate: vi.fn(),
}));

vi.mock("@/lib/analytics", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/analytics")>();
  return { ...real, registrarEvento: vi.fn() };
});

vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  // La tarjeta de familias tecnológicas mira el rol para decidir si los
  // controles van deshabilitados: aquí, `member` (solo lectura).
  useOrganizations: () => ({ data: [{ id: 7, name: "Equipo", role: "member" }] }),
}));

import MiPerfilPage from "@/app/(dashboard)/mi-perfil/page";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { registrarEvento } from "@/lib/analytics";

const perfilGet = vi.mocked(fetchWithAuth);
const mutar = vi.mocked(apiMutate);
const eventos = vi.mocked(registrarEvento);

function renderPagina() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <MiPerfilPage />
    </QueryClientProvider>,
  );
}

/**
 * Ensucia el formulario sin tocar un slider.
 *
 * El botón «Guardar» exige `dirty` y una suma de 100; los pesos por defecto ya
 * suman 100, así que basta con escribir en un campo. Arrastrar un `Slider` de
 * Radix en jsdom mediría el ratón, no el embudo.
 */
function ensuciarFormulario() {
  fireEvent.change(screen.getByLabelText("Mínimo (€)"), { target: { value: "50000" } });
}

async function guardar() {
  const boton = await screen.findByRole("button", { name: "Guardar perfil" });
  fireEvent.click(boton);
  await waitFor(() => expect(mutar).toHaveBeenCalled());
}

describe("MiPerfilPage — telemetría de activación", () => {
  beforeEach(() => {
    cleanup();
    window.localStorage.clear();
    eventos.mockClear();
    mutar.mockReset();
    mutar.mockResolvedValue({});
    perfilGet.mockReset();
    // El objeto vacío es lo que devuelve la API para quien no tiene perfil.
    perfilGet.mockResolvedValue({});
  });

  afterEach(() => {
    cleanup();
  });

  it("guardar el perfil por primera vez emite la activación", async () => {
    renderPagina();
    await screen.findByRole("button", { name: "Guardar perfil" });
    ensuciarFormulario();
    await guardar();

    await waitFor(() =>
      expect(eventos).toHaveBeenCalledWith("perfil_configurado", { primera_vez: "si" }),
    );
    expect(mutar).toHaveBeenCalledWith(
      "PUT",
      "/api/v1/me/profile",
      expect.objectContaining({ organization_id: 7, visibility: "private" }),
    );
  });

  it("el segundo guardado es reajuste, no activación", async () => {
    renderPagina();
    await screen.findByRole("button", { name: "Guardar perfil" });
    ensuciarFormulario();
    await guardar();
    cleanup();

    eventos.mockClear();
    mutar.mockClear();
    renderPagina();
    await screen.findByRole("button", { name: "Guardar perfil" });
    ensuciarFormulario();
    await guardar();

    await waitFor(() =>
      expect(eventos).toHaveBeenCalledWith("perfil_configurado", { primera_vez: "no" }),
    );
  });

  it("no manda nada del contenido del perfil", async () => {
    renderPagina();
    await screen.findByRole("button", { name: "Guardar perfil" });
    const campoKeyword = screen.getByPlaceholderText(/consultoría, mantenimiento/);
    fireEvent.change(campoKeyword, { target: { value: "sap" } });
    // Enter y no el botón: hay dos «Añadir» en la página (keywords y CPVs).
    fireEvent.keyDown(campoKeyword, { key: "Enter" });
    ensuciarFormulario();
    await guardar();

    await waitFor(() => expect(eventos).toHaveBeenCalled());
    const [, propiedades] = eventos.mock.calls[0];
    // La keyword que se acaba de escribir sí viaja al backend (es su sitio) y
    // no puede aparecer en la métrica: se comprueba la forma exacta del
    // payload, no la ausencia de una palabra concreta.
    expect(Object.keys(propiedades)).toEqual(["primera_vez"]);
  });

  it("un guardado fallido no cuenta como activación", async () => {
    mutar.mockRejectedValue(new Error("500"));
    renderPagina();
    await screen.findByRole("button", { name: "Guardar perfil" });
    ensuciarFormulario();
    await guardar();

    await waitFor(() => expect(mutar).toHaveBeenCalled());
    expect(eventos).not.toHaveBeenCalled();
  });
});
