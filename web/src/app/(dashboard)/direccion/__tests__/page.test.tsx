/**
 * Dirección: qué pide cada vista y cómo enseña lo que llega.
 *
 * Lo que fija este suite:
 * - El cuadro se pide para la organización activa y con la ventana de la URL
 *   (por defecto, 12 meses). Sin `organization_id` el backend resolvía la
 *   personal y la pantalla salía vacía para un owner.
 * - Cada vista pide sólo lo suyo: Actividad no espera ni depende del cuadro.
 * - Las cifras llegan hechas: la pantalla enseña valor, diferencia y nota,
 *   y por debajo del mínimo el hueco, nunca un número.
 * - Sin base en el histórico hay un único aviso con lo que falta registrar.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));
import { irA, router } from "@/test/navegacion-superficial";

const { apiGet, ApiError, vista, rol } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  vista: { actual: "resultado" },
  rol: { actual: "owner" as string | undefined },
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      message: string,
    ) {
      super(message);
    }
  },
}));

vi.mock("@/lib/api-client", () => ({ apiGet, ApiError }));
vi.mock("@/hooks/use-organization", () => ({
  // Réplica de la real: `undefined` es «todavía no se sabe»; `null`, «no hay
  // ninguna», que sí es una respuesta y deja pasar la consulta.
  organizacionResuelta: (id: unknown) => id !== undefined,
  useActiveOrganizationId: () => 21,
  useOrganizationMembers: () => ({ data: [] }),
  useRolActivo: () => rol.actual,
}));
vi.mock("@/components/layout/space-shell", () => ({
  useSpaceView: () => ({ view: vista.actual, setView: vi.fn() }),
  SpaceShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

import DireccionPage from "@/app/(dashboard)/direccion/page";

function tarjeta(extra: Record<string, unknown>) {
  return { n: 0, n_minimo: 1, universo: "Universo de prueba.", nota: null, ...extra };
}

function cuadro(extra: Record<string, unknown> = {}) {
  return {
    organization_id: 21,
    periodo_desde: "2025-10-09T00:00:00Z",
    anterior_desde: "2024-10-09T00:00:00Z",
    n_minimo: 5,
    cierres: 12,
    cierres_historico: 30,
    tarjetas: [],
    cortes: [],
    perdidas: 0,
    perdidas_n_minimo: 5,
    perdidas_por_motivo: [],
    pendientes_resultado: 0,
    radar_quality: null,
    ...extra,
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <DireccionPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  irA("/direccion");
});

afterEach(() => {
  cleanup();
  apiGet.mockReset();
  vi.clearAllMocks();
  vista.actual = "resultado";
  rol.actual = "owner";
});

function llamadasA(ruta: string) {
  return apiGet.mock.calls.filter(([path]) => path === ruta);
}

describe("Dirección › Resultado", () => {
  it("pide el cuadro de la organización activa con la ventana de 12 meses", async () => {
    apiGet.mockResolvedValue(cuadro());
    renderPage();

    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    const [, opciones] = llamadasA("/api/v1/pursuits/direccion")[0];
    expect(opciones.params.query.organization_id).toBe(21);
    expect(opciones.params.query.period_from).toMatch(/^\d{4}-\d{2}-\d{2}T00:00:00/);
    expect(opciones.params.query.period_to).toBeUndefined();
    expect(await screen.findByText(/frente al mismo periodo de hace un año/)).toBeTruthy();
  });

  it("cambiar de periodo reescribe la URL sin navegar y pide la ventana nueva", async () => {
    apiGet.mockResolvedValue(cuadro());
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Histórico" }));

    await waitFor(() => expect(window.location.search).toBe("?periodo=historico"));
    await waitFor(() =>
      expect(llamadasA("/api/v1/pursuits/direccion").at(-1)?.[1].params.query.period_from).toBeUndefined(),
    );
    expect(router.push).not.toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("enseña la cifra con su diferencia y, sin base, la nota en vez de un número", async () => {
    apiGet.mockResolvedValue(
      cuadro({
        tarjetas: [
          tarjeta({
            clave: "tasa_exito",
            etiqueta: "Tasa de éxito",
            valor: 0.4,
            unidad: "pct",
            n: 12,
            n_minimo: 5,
            anterior: 0.3,
            n_anterior: 9,
            delta: 0.1,
            mejor_si: "sube",
          }),
          tarjeta({
            clave: "ciclo_dias",
            etiqueta: "Ciclo de identificada a cerrada (mediana)",
            valor: null,
            unidad: "dias",
            n: 2,
            n_minimo: 5,
            n_anterior: 1,
            anterior: null,
            mejor_si: "baja",
            nota: "Sin base: 2 cierre(s) con fechas; hacen falta 5.",
          }),
          tarjeta({
            clave: "valor_ponderado",
            etiqueta: "Valor ponderado del pipeline",
            valor: 50000,
            unidad: "eur",
            n: 3,
            depende_del_periodo: false,
          }),
        ],
      }),
    );
    renderPage();

    expect(await screen.findByText("40 %")).toBeTruthy();
    expect(screen.getByText("+10 pp frente a 30 % hace un año")).toBeTruthy();
    expect(screen.getByText("Sin base")).toBeTruthy();
    expect(screen.getByText("Sin base: 2 cierre(s) con fechas; hacen falta 5.")).toBeTruthy();
    expect(screen.getByText("Hace un año, sin base (n = 1).")).toBeTruthy();
    expect(screen.getByText(/50\.000\s€/)).toBeTruthy();
    expect(screen.getByText("Foto de hoy: no depende del periodo.")).toBeTruthy();
    expect(screen.getByText(/n = 2 \(mínimo 5\)/)).toBeTruthy();
    expect(screen.getAllByText("Cómo se calcula")).toHaveLength(3);
  });

  it("los cortes llevan su posición frente a la media y pliegan lo que no tiene base", async () => {
    apiGet.mockResolvedValue(
      cuadro({
        cortes: [
          {
            clave: "organo",
            titulo: "Órgano",
            media: 0.4,
            filas: [
              { clave: "Ayuntamiento de Madrid", valor: 0.8, n: 10, intervalo_bajo: 0.49, intervalo_alto: 0.94, posicion: "por_encima" },
            ],
            filas_sin_base: [
              { clave: "Diputación de Soria", n: 2 },
              { clave: "Ayuntamiento de Segovia", n: 1 },
            ],
            cierres_sin_base: 3,
          },
        ],
      }),
    );
    renderPage();

    const enlace = await screen.findByRole("link", { name: "Ayuntamiento de Madrid" });
    expect(enlace.getAttribute("href")).toBe("/mercado?vista=organos&organo_q=Ayuntamiento%20de%20Madrid");
    expect(screen.getByText("80 %")).toBeTruthy();
    expect(screen.getByText(/Por encima de la media/)).toBeTruthy();
    expect(screen.getByText(/Margen 49–94 %/)).toBeTruthy();
    expect(screen.getByText("Y 2 con menos de 5 cierres (3 cierres en total)")).toBeTruthy();
  });

  it("sin base en el histórico da un solo aviso con lo que falta registrar", async () => {
    apiGet.mockResolvedValue(
      cuadro({
        cierres: 1,
        cierres_historico: 2,
        pendientes_resultado: 1,
        pendientes_resultado_muestra: [
          { pursuit_id: 7, licitacion_id: "ES-7", titulo: "Soporte SAP", desde: "2026-05-01", dias: 160 },
        ],
      }),
    );
    renderPage();

    expect(await screen.findByText("Dirección empieza a publicar con 5 cierres")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Soporte SAP" }).getAttribute("href")).toBe("/oportunidades/7");
    expect(screen.getByText("presentada hace 160 días")).toBeTruthy();
    expect(screen.queryByText("Dónde ganamos")).toBeNull();
  });

  it("con base en el histórico pero no en el periodo ofrece el histórico", async () => {
    apiGet.mockResolvedValue(cuadro({ cierres: 2, cierres_historico: 30 }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Ver el histórico (30 cierres)" }));
    await waitFor(() => expect(window.location.search).toBe("?periodo=historico"));
  });

  it("un 403 se explica como rol, no como caída", async () => {
    apiGet.mockRejectedValue(new ApiError(403, "Forbidden"));
    renderPage();

    expect(await screen.findByText("Dirección es solo para propietarios y administradores")).toBeTruthy();
  });

  it("con el rol ya conocido, un member ve el aviso sin pedir nada", async () => {
    rol.actual = "member";
    renderPage();

    expect(await screen.findByText("Dirección es solo para propietarios y administradores")).toBeTruthy();
    expect(apiGet).not.toHaveBeenCalled();
  });
});

describe("Dirección › otras vistas", () => {
  it("Actividad pide sólo el feed: ni espera al cuadro ni cae con él", async () => {
    vista.actual = "actividad";
    apiGet.mockImplementation((path: string) =>
      path === "/api/v1/pursuits/actividad"
        ? Promise.resolve({ organization_id: 21, items: [], siguiente_cursor: null, filtrado_por_rol: false })
        : Promise.reject(new ApiError(500, "caído")),
    );
    renderPage();

    expect(await screen.findByText("Sin actividad")).toBeTruthy();
    expect(llamadasA("/api/v1/pursuits/direccion")).toHaveLength(0);
  });

  it("Carga del equipo pide la carga y enseña una fila por persona", async () => {
    vista.actual = "carga";
    apiGet.mockResolvedValue({
      organization_id: 21,
      hoy: "2026-10-09",
      horizonte_dias: 14,
      total_abiertas: 3,
      truncado: false,
      responsables: [
        { user_id: 1, nombre: "Ana López", abiertas: 3, presentadas: 1, plazos_proximos: 1, plazos_vencidos: 0, sin_proxima_accion: 2, acciones_vencidas: 0 },
        { user_id: 2, nombre: "Luis Pérez", abiertas: 0, presentadas: 0, plazos_proximos: 0, plazos_vencidos: 0, sin_proxima_accion: 0, acciones_vencidas: 0 },
      ],
    });
    renderPage();

    expect(await screen.findByText("Ana López")).toBeTruthy();
    expect(screen.getByText("Luis Pérez")).toBeTruthy();
    expect(screen.getByText("Plazo en 14 días")).toBeTruthy();
    expect(llamadasA("/api/v1/pursuits/direccion/carga")[0][1]).toEqual({
      params: { query: { organization_id: 21 } },
    });
  });
});
