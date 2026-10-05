/**
 * El inspector de /detalle: lo que decide si mirar una licitación va arriba,
 * sin pestañas, y el resto se reparte en cinco.
 *
 * Se fija lo que motivó el rediseño: la fecha límite y el órgano estaban por
 * debajo de cinco bloques de la pestaña Resumen, y la cabecera solo enseñaba
 * el importe.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { LicitacionDetail } from "@/lib/licitacion-detail";

const { fetchWithAuth } = vi.hoisted(() => ({ fetchWithAuth: vi.fn() }));

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  fetchWithAuth,
}));
vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  organizacionResuelta: () => true,
}));
// El seguimiento tiene su propio test (`seguir-boton`); aquí solo importa que
// esté entre las acciones.
vi.mock("@/components/seguir-boton", () => ({
  SeguirBoton: () => (
    <button type="button" aria-pressed={false}>
      Seguir
    </button>
  ),
}));

import { DetailInspector } from "@/components/detail-inspector";

const DIA = 86_400_000;

function licitacion(extra: Partial<LicitacionDetail> = {}): LicitacionDetail {
  return {
    id_externo: "PLACSP-1",
    titulo: "Mantenimiento de la plataforma de tramitación",
    organo_contratacion: "Dirección General de Sistemas",
    importe: 1_248_000,
    estado: "PUB",
    fecha_publicacion: "2026-09-22",
    ccaa: "Andalucía",
    cpv: "72267000",
    url: "https://contrataciondelestado.es/x",
    fuente: "placsp",
    tecnologia: "Administración electrónica",
    tipo_contrato: null,
    provincia: "Sevilla",
    // Relativa al reloj: `plazoVisual` cuenta los días desde ahora.
    fecha_limite: new Date(Date.now() + 8 * DIA).toISOString(),
    fecha_inicio: "2027-01-01",
    fecha_fin: "2028-12-31",
    descripcion: "Soporte de segundo nivel.",
    score: 78.4,
    band: "Caliente",
    score_desglose: { importe: 82, plazo: 64 },
    risk_flags: ["organo_anula_frecuente"],
    ...extra,
  };
}

function responder(url: string): Promise<unknown> {
  if (url.includes("/prediccion-baja")) {
    return Promise.resolve({ licitacion_id: "PLACSP-1", p10: 0.061, p50: 0.124, p90: 0.198, serving: "modelo", model_version: "3" });
  }
  if (url.includes("/competencia-esperada")) {
    return Promise.resolve({
      licitacion_id: "PLACSP-1",
      calculado_en: "2026-10-04",
      ofertas: { ventana_meses: 24, estimacion: 4 },
      incumbente: null,
      rivales: { items: [] },
    });
  }
  if (url.includes("/resoluciones")) return Promise.resolve({ items: [] });
  // El resto de bloques se quedan cargando: no son lo que se mira aquí.
  return new Promise(() => {});
}

function pintar(props: { onExpandir?: () => void } = {}, extra?: Partial<LicitacionDetail>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <DetailInspector licitacion={licitacion(extra)} onClose={() => {}} {...props} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchWithAuth.mockImplementation((url: string) => responder(url));
});

afterEach(() => {
  cleanup();
  fetchWithAuth.mockReset();
});

describe("DetailInspector", () => {
  it("pone el órgano, el lugar y la fecha límite en la cabecera", () => {
    pintar();
    const ficha = screen.getByRole("complementary", { name: "Ficha de la licitación" });
    expect(within(ficha).getByRole("heading", { name: /Mantenimiento de la plataforma/ })).toBeInTheDocument();
    expect(within(ficha).getByText("Dirección General de Sistemas")).toBeInTheDocument();
    expect(within(ficha).getByText("Sevilla, Andalucía")).toBeInTheDocument();
    expect(within(ficha).getByText("Fecha límite")).toBeInTheDocument();
    expect(within(ficha).getByText("8 d para cierre")).toBeInTheDocument();
    expect(within(ficha).getByText("Ejecución de 24 meses")).toBeInTheDocument();
    expect(within(ficha).getByText("78,4")).toBeInTheDocument();
    expect(within(ficha).getByText("Órgano que anula a menudo")).toBeInTheDocument();
  });

  it("enseña la baja esperada como estimación", async () => {
    pintar();
    expect(await screen.findByText("12,4%")).toBeInTheDocument();
    expect(screen.getByText("Intervalo 80%: 6,1% – 19,8%")).toBeInTheDocument();
    expect(screen.getAllByText("Estimación").length).toBeGreaterThan(0);
  });

  it("sin puntuación, la cuarta cifra son las ofertas esperadas", async () => {
    pintar({}, { score: undefined, band: null, score_desglose: undefined });
    expect(screen.queryByText("Puntuación")).not.toBeInTheDocument();
    expect(await screen.findByText("~4")).toBeInTheDocument();
  });

  it("reparte el resto en cinco pestañas y Competencia trae la competencia esperada", async () => {
    pintar();
    const pestanas = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(pestanas).toEqual(["Resumen", "Competencia", "Pliegos", "IA", "Recursos"]);

    fireEvent.click(screen.getByRole("tab", { name: "Competencia" }));
    expect(screen.getByRole("tab", { name: "Competencia" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("heading", { name: "Competencia esperada" })).toBeInTheDocument();
  });

  it("«Preguntar a la IA» lleva a la pestaña IA", async () => {
    pintar();
    fireEvent.click(screen.getByRole("button", { name: "Preguntar a la IA" }));
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "IA" })).toHaveAttribute("aria-selected", "true"),
    );
  });

  it("abre la ficha completa solo si la pantalla la ofrece", () => {
    const onExpandir = vi.fn();
    pintar({ onExpandir });
    fireEvent.click(screen.getByRole("button", { name: "Abrir la ficha completa" }));
    expect(onExpandir).toHaveBeenCalledOnce();

    cleanup();
    pintar();
    expect(screen.queryByRole("button", { name: "Abrir la ficha completa" })).not.toBeInTheDocument();
  });
});
