import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * La página entera, por lo que el rediseño cambió de ella:
 *
 * - un solo formulario y una sola acción de guardar: los ajustes de la
 *   organización y los datos de la cuenta se van a su sitio y aquí queda el
 *   enlace;
 * - primero qué te interesa y después cuánto pesa;
 * - nada destructivo a un clic, y nada que se pierda sin avisar;
 * - y el efecto de lo que se toca, a la vista antes de guardar.
 */

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));

const PROPUESTA_INSUFICIENTE = {
  estado: "insuficiente",
  n_cierres: 0,
  n_ganadas: 0,
  n_perdidas: 0,
  minimo_cierres: 20,
  organization_id: 7,
  origen_pesos_actuales: "global",
  pesos_actuales: {},
  dimensiones: [],
};

vi.mock("@/lib/api-client", () => ({
  fetchWithAuth: vi.fn(),
  apiMutate: vi.fn(),
  apiGet: vi.fn(),
}));
vi.mock("@/lib/analytics", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/analytics")>();
  return { ...real, registrarEvento: vi.fn() };
});
vi.mock("@/hooks/use-organization", () => ({
  organizacionResuelta: (id: unknown) => id !== undefined,
  useActiveOrganizationId: () => 7,
  useOrganizations: () => ({ data: [{ id: 7, name: "Equipo", role: "member" }] }),
}));

import MiPerfilPage from "@/app/(dashboard)/mi-perfil/page";
import { apiGet, apiMutate, fetchWithAuth } from "@/lib/api-client";
import { irA } from "@/test/navegacion-superficial";

const pedir = vi.mocked(fetchWithAuth);
const mutar = vi.mocked(apiMutate);
const propuesta = vi.mocked(apiGet);

const PREVIA = {
  total_scored: 31,
  afinidad_origen: "perfil",
  opportunities: [
    {
      id_externo: "L1",
      titulo: "Mantenimiento de SAP S/4HANA",
      organo_contratacion: "Ayuntamiento de Vigo",
      importe: 250_000,
      fecha_limite: "2026-11-20",
      score: 82,
      band: "Caliente",
      posicion: 1,
      score_actual: 64,
      posicion_actual: 2,
    },
    {
      id_externo: "L2",
      titulo: "Suministro de licencias",
      organo_contratacion: "Diputación de Lugo",
      importe: 90_000,
      fecha_limite: "2026-11-25",
      score: 61,
      band: "Atractiva",
      posicion: 2,
      score_actual: 70,
      posicion_actual: 1,
    },
  ],
  salen: [],
};

/** Lo que contesta cada ruta; el perfil guardado es lo que cambia entre casos. */
function servir(perfil: Record<string, unknown>) {
  pedir.mockImplementation(async (url: string) => {
    if (url.startsWith("/api/v1/me/profile/preview")) return PREVIA;
    if (url.startsWith("/api/v1/me/profile")) return perfil;
    if (url.endsWith("/settings")) {
      return { organization_id: 7, tecnologias: ["SAP", "ORACLE"], tecnologias_disponibles: ["ORACLE", "SAP"] };
    }
    if (url.startsWith("/api/v1/meta/filters")) {
      return { cpv_nombres: [{ codigo: "72000000", nombre: "Servicios TI: consultoría, desarrollo, internet" }] };
    }
    return {};
  });
}

function renderPagina() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <MiPerfilPage />
    </QueryClientProvider>,
  );
}

const guardarBoton = () => screen.findByText("Guardar perfil");
const ensuciar = () => fireEvent.change(screen.getByLabelText("Mínimo (€)"), { target: { value: "50000" } });

const PERFIL_PROPIO = {
  weights: { importe: 20, plazo: 15, competencia: 20, margen: 20, afinidad: 15, senal_tecnica: 10 },
  afinidad_keywords: ["sap"],
  cpvs: ["72000000"],
  importe_min: 1000,
  visibility: "private",
  inherited: false,
  updated_at: "2026-09-06T16:57:21+00:00",
};

beforeEach(() => {
  irA("/mi-perfil");
  mutar.mockReset();
  mutar.mockResolvedValue({});
  propuesta.mockReset();
  propuesta.mockResolvedValue(PROPUESTA_INSUFICIENTE);
  pedir.mockReset();
  servir({});
});
afterEach(() => cleanup());

describe("Mi perfil · qué hay en la página", () => {
  it("pregunta primero qué te interesa y después cuánto pesa", async () => {
    renderPagina();
    await guardarBoton();

    const titulos = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(titulos.indexOf("Qué te interesa")).toBeGreaterThanOrEqual(0);
    expect(titulos.indexOf("Qué te interesa")).toBeLessThan(titulos.indexOf("Cuánto pesa cada criterio"));
  });

  it("no edita ajustes de la organización ni borra la cuenta: enlaza a donde viven", async () => {
    renderPagina();
    await guardarBoton();

    expect(screen.queryByText("Tecnologías de tu organización")).not.toBeInTheDocument();
    expect(screen.queryByText("Informe semanal por correo")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Eliminar mis datos/ })).not.toBeInTheDocument();
    // Una sola acción de guardar en toda la página.
    expect(screen.getAllByRole("button", { name: /^Guardar/ })).toHaveLength(1);

    expect(screen.getByRole("link", { name: /Equipo › Organización/ })).toHaveAttribute("href", "/equipo");
    expect(screen.getByRole("link", { name: /Ajustes › Datos y cuenta/ })).toHaveAttribute(
      "href",
      "/ajustes?vista=cuenta",
    );
    // Lo que la organización decidió sigue a la vista, en lectura.
    expect(await screen.findByText("SAP, ORACLE")).toBeInTheDocument();
  });

  it("nombra los CPV guardados con el catálogo de la API", async () => {
    servir(PERFIL_PROPIO);
    renderPagina();

    expect(
      await screen.findByRole("button", { name: "Quitar 72000000, Servicios TI: consultoría, desarrollo, internet" }),
    ).toBeInTheDocument();
  });
});

describe("Mi perfil · palabras clave", () => {
  it("pegar varias separadas por comas las añade una a una", async () => {
    renderPagina();
    await guardarBoton();

    const campo = screen.getByLabelText("Nueva palabra clave de afinidad");
    fireEvent.change(campo, { target: { value: "SAP, s/4hana; abap, sap" } });
    fireEvent.keyDown(campo, { key: "Enter" });

    for (const palabra of ["sap", "s/4hana", "abap"]) {
      expect(screen.getByRole("button", { name: `Quitar ${palabra}` })).toBeInTheDocument();
    }
    fireEvent.click(await guardarBoton());
    await waitFor(() =>
      expect(mutar).toHaveBeenCalledWith(
        "PUT",
        "/api/v1/me/profile",
        expect.objectContaining({ afinidad_keywords: ["sap", "s/4hana", "abap"] }),
      ),
    );
  });
});

describe("Mi perfil · nada se pierde ni se borra sin avisar", () => {
  it("eliminar el perfil pide confirmación", async () => {
    servir(PERFIL_PROPIO);
    renderPagina();

    fireEvent.click(await screen.findByRole("button", { name: "Eliminar perfil" }));
    expect(mutar).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Sí, eliminar" }));
    await waitFor(() => expect(mutar).toHaveBeenCalledWith("DELETE", "/api/v1/me/profile"));
  });

  it("con cambios sin guardar no se puede aplicar la propuesta de pesos", async () => {
    propuesta.mockResolvedValue({
      ...PROPUESTA_INSUFICIENTE,
      estado: "propuesta",
      n_cierres: 24,
      n_ganadas: 14,
      n_perdidas: 10,
      origen_pesos_actuales: "perfil",
      pesos_actuales: { importe: 20 },
      pesos_propuestos: { importe: 24 },
      dimensiones: [
        { dimension: "importe", peso_actual: 20, peso_propuesto: 24, media_ganadas: 71, media_perdidas: 52, delta: 19 },
      ],
    });
    renderPagina();

    const aplicar = await screen.findByRole("button", { name: "Aplicar la propuesta" });
    expect(aplicar).not.toBeDisabled();

    ensuciar();

    await waitFor(() => expect(aplicar).toBeDisabled());
    expect(screen.getByText(/Guarda o descarta antes tus cambios/)).toBeInTheDocument();
  });

  it("descartar devuelve el formulario a lo guardado", async () => {
    servir(PERFIL_PROPIO);
    renderPagina();
    await waitFor(() => expect(screen.getByLabelText("Mínimo (€)")).toHaveValue(1000));

    ensuciar();
    // Por texto y no por `role=status`: mientras llega la vista previa, su
    // esqueleto también lo es.
    expect(await screen.findByText("Cambios sin guardar")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));

    await waitFor(() => expect(screen.getByLabelText("Mínimo (€)")).toHaveValue(1000));
    expect(await guardarBoton()).toBeDisabled();
    expect(mutar).not.toHaveBeenCalled();
  });

  it("salir por un enlace de la consola con cambios se para a preguntar", async () => {
    renderPagina();
    await guardarBoton();
    ensuciar();
    await screen.findByText("Cambios sin guardar");

    const enlace = screen.getByRole("link", { name: /Equipo › Organización/ });
    const clic = createEvent.click(enlace, { button: 0 });
    fireEvent(enlace, clic);

    expect(clic.defaultPrevented).toBe(true);
    expect(await screen.findByRole("dialog", { name: "Tienes cambios sin guardar" })).toBeInTheDocument();
  });
});

describe("Mi perfil · perfil heredado de la organización", () => {
  const HEREDADO = { ...PERFIL_PROPIO, visibility: "organization", inherited: true };

  it("dice de quién es lo que se ve y qué pasa al guardar", async () => {
    servir(HEREDADO);
    renderPagina();

    expect(await screen.findByText("Estás usando el perfil compartido de tu organización")).toBeInTheDocument();
    expect(screen.getByText(/Al guardar creas tu propio perfil/)).toBeInTheDocument();
    // No es suyo: no hay nada que eliminar.
    expect(screen.queryByRole("button", { name: "Eliminar perfil" })).not.toBeInTheDocument();
  });

  it("el perfil propio que nace de uno heredado es privado", async () => {
    servir(HEREDADO);
    renderPagina();
    await waitFor(() => expect(screen.getByLabelText("Mínimo (€)")).toHaveValue(1000));

    expect(screen.getByRole("switch", { name: "Compartir perfil con la organización" })).not.toBeChecked();
    ensuciar();
    fireEvent.click(await guardarBoton());

    await waitFor(() =>
      expect(mutar).toHaveBeenCalledWith(
        "PUT",
        "/api/v1/me/profile",
        expect.objectContaining({ visibility: "private", importe_min: 50000 }),
      ),
    );
  });
});

describe("Mi perfil · vista previa del Radar", () => {
  const previas = () => pedir.mock.calls.filter(([url]) => String(url).startsWith("/api/v1/me/profile/preview"));

  it("enseña cómo quedaría el Radar con lo que hay en pantalla, sin guardarlo", async () => {
    servir(PERFIL_PROPIO);
    renderPagina();

    const panel = await screen.findByRole("complementary", { name: "Vista previa del Radar" });
    expect(await within(panel).findByText("Mantenimiento de SAP S/4HANA", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(within(panel).getByText("sube 1 puesto")).toBeInTheDocument();

    // Se pregunta por el perfil guardado, tal cual se guardaría, y sin
    // escribir nada: ni PUT ni la visibilidad, que no cambia el orden.
    const [, opciones] = previas()[0];
    expect(opciones).toMatchObject({ method: "POST" });
    const cuerpo = JSON.parse(String(opciones?.body));
    expect(cuerpo).toMatchObject({
      weights: expect.objectContaining({ importe: 20, afinidad: 15 }),
      afinidad_keywords: ["sap"],
      cpvs: ["72000000"],
      importe_min: 1000,
      importe_max: null,
      organization_id: 7,
    });
    expect(cuerpo).not.toHaveProperty("visibility");
    expect(mutar).not.toHaveBeenCalled();
  });

  it("al cargar pide una sola vista previa, con el perfil guardado y no con los valores por defecto", async () => {
    servir(PERFIL_PROPIO);
    renderPagina();

    await waitFor(() => expect(previas()).toHaveLength(1), { timeout: 3000 });
    expect(JSON.parse(String(previas()[0][1]?.body)).afinidad_keywords).toEqual(["sap"]);
  });

  it("guardar vuelve a pedirla: el orden de hoy con el que se compara acaba de cambiar", async () => {
    servir(PERFIL_PROPIO);
    renderPagina();
    await waitFor(() => expect(previas()).toHaveLength(1), { timeout: 3000 });

    ensuciar();
    await waitFor(() => expect(previas()).toHaveLength(2), { timeout: 3000 });
    fireEvent.click(await guardarBoton());

    // El cuerpo es el mismo que el de la prueba, pero lo guardado ya no: sin
    // volver a preguntar, la lista seguiría diciendo «sube 6 puestos» sobre
    // un perfil que ya es el vigente.
    await waitFor(() => expect(previas()).toHaveLength(3), { timeout: 3000 });
    expect(previas()[2][1]?.body).toBe(previas()[1][1]?.body);
  });

  it("un cambio vuelve a preguntar con el valor nuevo", async () => {
    servir(PERFIL_PROPIO);
    renderPagina();
    await waitFor(() => expect(previas()).toHaveLength(1), { timeout: 3000 });

    ensuciar();

    await waitFor(() => expect(previas()).toHaveLength(2), { timeout: 3000 });
    expect(JSON.parse(String(previas()[1][1]?.body)).importe_min).toBe(50000);
  });
});
