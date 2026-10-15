/**
 * Mercado › Proyectos y módulos, por familias de la taxonomía (2026-10).
 *
 * Hasta 2026-10 la vista solo entendía módulos SAP. Lo que fija este suite:
 *
 * - La vista abre por **familias** (ERP, CRM, ciberseguridad…), con sus
 *   cifras hechas en el backend, y dice qué fabricantes no cuentan en ninguna.
 * - Los módulos SAP son el **desglose de ERP**, con su propio denominador (las
 *   licitaciones SAP), no el ámbito entero.
 * - Sigue siendo una vista experimental: la marca y la frase lo dicen.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ProyectosModulosResponse } from "../_hooks/use-proyectos-modulos-view";

const estado = vi.hoisted(() => ({ data: undefined as unknown, isLoading: false }));

vi.mock("@/hooks/use-filtered-query", () => ({
  useFilteredQuery: () => ({ data: estado.data, isLoading: estado.isLoading, error: null, refetch: vi.fn() }),
}));
vi.mock("@/hooks/use-feature-flag", () => ({ useFeatureFlag: () => ({ enabled: true, estado: "activo" }) }));
vi.mock("@/components/export-popover", () => ({ ExportPopover: () => null }));
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

import { TooltipProvider } from "@/components/ui/tooltip";
import Vista from "../_components/proyectos-modulos-view";

/** La vista con lo que el layout del dashboard le pone alrededor. */
function ProyectosModulosView() {
  return (
    <TooltipProvider>
      <Vista />
    </TooltipProvider>
  );
}

const DATOS: ProyectosModulosResponse = {
  familias: [
    { familia: "ERP", etiqueta: "ERP", count: 30, importe: 9_000_000, importe_medio: 300_000 },
    {
      familia: "CIBERSEGURIDAD",
      etiqueta: "Ciberseguridad",
      count: 12,
      importe: 2_400_000,
      importe_medio: 200_000,
    },
    { familia: "CRM", etiqueta: "CRM", count: 5, importe: 4_000_000, importe_medio: 800_000 },
  ],
  total: 100,
  total_con_familia: 44,
  menciones_familia: 47,
  pct_con_familia: 44,
  familias_por_licitacion: 1.07,
  importe_con_familia: 14_000_000,
  ticket_medio_familia: 318_181.82,
  top_familia_yoy: { familia: "CIBERSEGURIDAD", etiqueta: "Ciberseguridad", crecimiento_pct: 50, n_act: 9 },
  fabricantes_sin_familia: ["IBM", "Microsoft Dynamics / Azure", "Oracle", "ServiceNow", "Sopra"],
  modulos: [
    { modulo: "S/4HANA", count: 8, importe: 4_000_000 },
    { modulo: "Ariba", count: 3, importe: 600_000 },
  ],
  total_sap: 20,
  total_clasificados: 10,
  menciones_modulo: 11,
  pct_sap_con_modulo: 50,
  modulos_por_clasificada: 1.1,
  importe_total_sap: 4_400_000,
  ticket_medio_sap: 440_000,
  top_modulo_yoy: { modulo: "Ariba", crecimiento_pct: 999, n_act: 3 },
  tipos_proyecto: [{ tipo: "Servicios", count: 60, importe: 10_000_000 }],
  tipo_estado: [{ tipo: "Servicios", estado: "Publicada", n: 60 }],
  cpv: [{ cpv: "72000000", cpv_desc: "Servicios TI", count: 40, importe: 8_000_000 }],
};

beforeEach(() => {
  estado.data = DATOS;
  estado.isLoading = false;
});
afterEach(cleanup);

describe("Proyectos y módulos", () => {
  it("abre por familias tecnológicas y sigue marcada como experimental", () => {
    render(<ProyectosModulosView />);

    expect(screen.getByRole("note")).toHaveTextContent(/familia tecnológica/);
    expect(screen.getByRole("heading", { name: "Por familia tecnológica" })).toBeInTheDocument();
    // Las cifras de cabecera son las del backend, con su denominador.
    expect(screen.getByText("Licitaciones con familia")).toBeInTheDocument();
    expect(screen.getByText("44% de 100 del ámbito")).toBeInTheDocument();
    expect(screen.getByText("Familia que más crece")).toBeInTheDocument();
    expect(screen.getAllByText("Ciberseguridad").length).toBeGreaterThan(0);
    // La vista ya no habla de «encaje con tu portfolio»: era solo de SAP.
    expect(screen.queryByText(/portfolio/i)).not.toBeInTheDocument();
  });

  it("dice qué fabricantes no cuentan en ninguna familia, en vez de esconderlos", () => {
    render(<ProyectosModulosView />);

    expect(
      screen.getByText(
        /IBM, Microsoft Dynamics \/ Azure, Oracle, ServiceNow y Sopra no cuentan en ninguna familia/,
      ),
    ).toBeInTheDocument();
  });

  it("la tabla de familias se ordena por importe al pulsar su cabecera", () => {
    render(<ProyectosModulosView />);

    const tabla = screen.getByRole("table", { name: "Familias" });
    const nombres = () =>
      within(tabla)
        .getAllByRole("row")
        .slice(1)
        .map((fila) => within(fila).getAllByRole("cell")[0].textContent);
    // Entra por licitaciones, de más a menos.
    expect(nombres()).toEqual(["ERP", "Ciberseguridad", "CRM"]);

    fireEvent.click(within(tabla).getByRole("button", { name: /Importe total/ }));
    expect(nombres()).toEqual(["ERP", "CRM", "Ciberseguridad"]);
  });

  it("los módulos SAP son el desglose de ERP, sobre las licitaciones SAP", () => {
    render(<ProyectosModulosView />);

    const erp = screen.getByRole("region", { name: "ERP por dentro: módulos SAP" });
    expect(within(erp).getByText("Licitaciones SAP")).toBeInTheDocument();
    expect(within(erp).getByText("10 con módulo detectado (50%)")).toBeInTheDocument();
    expect(within(erp).getByText("Módulo que más crece")).toBeInTheDocument();
    expect(within(erp).getByText("Nuevo este año · 3 licitaciones")).toBeInTheDocument();
    expect(within(erp).getByRole("table", { name: "Módulos SAP" })).toBeInTheDocument();
  });

  it("sin licitaciones con familia lo dice, sin tabla de ceros", () => {
    estado.data = { ...DATOS, familias: [], total_con_familia: 0, menciones_familia: 0, top_familia_yoy: null };
    render(<ProyectosModulosView />);

    expect(screen.getAllByText(/Ninguna licitación del ámbito actual es de una familia/).length).toBeGreaterThan(0);
  });
});
