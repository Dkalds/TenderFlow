/**
 * La ficha completa de /detalle: el marco (volver, anterior/siguiente, carga y
 * error) y lo que enseña sin pestañas.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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
vi.mock("@/components/seguir-boton", () => ({
  SeguirBoton: () => (
    <button type="button" aria-pressed={false}>
      Seguir
    </button>
  ),
}));

import { DetalleFichaCompleta } from "../_components/detalle-ficha-completa";
import type { PasosDeFicha } from "../_hooks/use-ficha-completa";

const LICITACION: LicitacionDetail = {
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
  tecnologia: null,
  tipo_contrato: null,
  provincia: "Sevilla",
  fecha_limite: "2026-10-13",
  fecha_inicio: "2027-01-01",
  fecha_fin: "2028-12-31",
  descripcion: null,
  score: 78.4,
  band: "Caliente",
};

const SIN_PASOS: PasosDeFicha = { posicion: null, anterior: null, siguiente: null };

function pintar(props: Partial<React.ComponentProps<typeof DetalleFichaCompleta>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const handlers = { onIr: vi.fn(), onVolver: vi.fn(), onReintentar: vi.fn() };
  render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <DetalleFichaCompleta
          idExterno="PLACSP-1"
          licitacion={LICITACION}
          error={null}
          pasos={SIN_PASOS}
          {...handlers}
          {...props}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return handlers;
}

beforeEach(() => {
  // Los bloques de la ficha se quedan cargando: aquí se mira el marco.
  fetchWithAuth.mockImplementation(() => new Promise(() => {}));
});

afterEach(() => {
  cleanup();
  fetchWithAuth.mockReset();
});

describe("DetalleFichaCompleta", () => {
  it("enseña la cabecera, las cifras y el calendario sin pestañas", () => {
    pintar();
    const ficha = screen.getByRole("article", { name: /Mantenimiento de la plataforma/ });
    expect(within(ficha).getByText("Dirección General de Sistemas")).toBeInTheDocument();
    expect(within(ficha).getByText("Ofertas esperadas")).toBeInTheDocument();
    const calendario = within(ficha).getByRole("list", { name: "Calendario del expediente" });
    expect(within(calendario).getByText("Hoy")).toBeInTheDocument();
    expect(within(calendario).getByText("Fin")).toBeInTheDocument();
    expect(within(ficha).getByText("Comunidad autónoma")).toBeInTheDocument();
    expect(screen.queryByRole("tablist", { name: "Secciones de la ficha" })).not.toBeInTheDocument();
  });

  it("pasa a la anterior o la siguiente de la página, y dice dónde está", () => {
    const pasos: PasosDeFicha = {
      posicion: { indice: 2, total: 25 },
      anterior: { indice: 1, id: "A" },
      siguiente: null,
    };
    const { onIr } = pintar({ pasos });
    expect(screen.getByText("3 de 25 en esta página")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Licitación anterior" }));
    expect(onIr).toHaveBeenCalledWith({ indice: 1, id: "A" });

    const siguiente = screen.getByRole("button", { name: "Licitación siguiente" });
    expect(siguiente).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(siguiente);
    expect(onIr).toHaveBeenCalledOnce();
  });

  it("«Volver a la tabla» sale de la ficha", () => {
    const { onVolver } = pintar();
    fireEvent.click(screen.getByRole("button", { name: "Volver a la tabla" }));
    expect(onVolver).toHaveBeenCalledOnce();
  });

  it("mientras carga reserva el alto, y un fallo se dice con Reintentar", () => {
    pintar({ licitacion: null });
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    cleanup();

    const { onReintentar } = pintar({ licitacion: null, error: new Error("boom") });
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo cargar la licitación");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(onReintentar).toHaveBeenCalledOnce();
  });
});
