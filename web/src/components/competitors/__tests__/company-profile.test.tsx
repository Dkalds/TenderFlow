import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildExecutiveSummary, cpvFamilyLabel, type CompanyProfileData } from "../company-profile-types";
import { CompanyYearTrend } from "../company-year-trend";

const profile: CompanyProfileData = {
  empresa: {
    empresa_id: 7,
    nombre: "Ejemplo Digital",
    nif: "B12345678",
    es_ute: false,
    grupo: null,
  },
  scope: {
    fecha_desde: "2025-01-01",
    fecha_hasta: "2025-12-31",
    cpv: null,
    ccaas: [],
    tecnologias: [],
    importe_min: null,
  },
  actividad_historica: {
    contratos: 8,
    importe_total: 900000,
    primera_adjudicacion: "2022-01-01",
    ultima_adjudicacion: "2025-10-01",
  },
  totales: {
    contratos: 4,
    importe_total: 500000,
    importe_mediano: 100000,
    ofertas_medias: 2.5,
    baja_media_pct: 12,
    pct_oferta_unica: 25,
    cobertura_ofertas_pct: 100,
    primera_adjudicacion: "2022-01-01",
    ultima_adjudicacion: "2025-10-01",
    organos: 2,
    territorios: 2,
    familias_cpv: 1,
  },
  posicion_mercado: {
    rank: 3,
    empresas: 20,
    cuota_pct: 8,
    importe_segmento: 6250000,
  },
  comparacion: {
    desde: "2025-01-01",
    hasta: "2025-12-31",
    anterior_desde: "2024-01-01",
    anterior_hasta: "2024-12-31",
    contratos: 4,
    contratos_anterior: 3,
    variacion_contratos_pct: 33.3,
    importe: 500000,
    importe_anterior: 400000,
    variacion_importe_pct: 25,
  },
  concentracion_clientes: {
    organo_principal: "Ministerio de Ejemplo",
    top1_contratos_pct: 50,
    top1_importe_pct: 60,
    top3_importe_pct: 100,
  },
  por_cpv: [
    {
      codigo: "72",
      label: "CPV 72",
      contratos: 4,
      importe: 500000,
      cuota_empresa_pct: 100,
    },
  ],
  por_ccaa: [
    {
      codigo: null,
      label: "Madrid",
      contratos: 3,
      importe: 400000,
      cuota_empresa_pct: 80,
    },
  ],
  organos_principales: [],
  por_anio: [],
  movimientos: [],
};

describe("company profile presentation helpers", () => {
  it("translates known CPV families", () => {
    expect(cpvFamilyLabel("72")).toBe("Servicios TI y consultoría tecnológica");
    expect(cpvFamilyLabel("99")).toBe("Familia CPV 99");
  });

  it("builds an operational summary with specialization, territory, client and trend", () => {
    const summary = buildExecutiveSummary(profile);
    expect(summary).toContain("Servicios TI y consultoría tecnológica");
    expect(summary).toContain("Madrid");
    expect(summary).toContain("Ministerio de Ejemplo");
    expect(summary).toContain("crece un 25.0%");
  });

  it("marks the current year as partial instead of presenting a misleading annual delta", () => {
    const currentYear = new Date().getFullYear();
    render(
      <CompanyYearTrend
        rows={[
          { anio: currentYear - 1, contratos: 4, importe: 200000 },
          { anio: currentYear, contratos: 2, importe: 100000 },
        ]}
      />,
    );
    expect(screen.getByText("Año en curso · dato parcial")).toBeInTheDocument();
  });
});
