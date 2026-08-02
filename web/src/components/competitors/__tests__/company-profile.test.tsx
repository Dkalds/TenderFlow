import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { initialCompanyProfilePeriod } from "../company-profile";
import { CompanyQuickView } from "../company-quick-view";
import {
  buildExecutiveSummary,
  cpvFamilyLabel,
  type CompanyAwardsData,
  type CompanyProfileData,
} from "../company-profile-types";
import { CompanyYearTrend } from "../company-year-trend";

const profile: CompanyProfileData = {
  empresa: {
    empresa_id: 7,
    nombre: "Ejemplo Digital",
    nif: "B12345678", // pragma: allowlist secret
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

const recentAwards: CompanyAwardsData = {
  items: [
    {
      licitacion_id: "EXP-2025-001",
      titulo: "Servicio de soporte y evolución de sistemas",
      organo_contratacion: "Ministerio de Ejemplo",
      fecha_adjudicacion: "2025-10-01",
      cpv: "72000000",
      ccaa: "Madrid",
      tecnologia: null,
      presupuesto_licitacion: 150000,
      importe_adjudicado: 120000,
      baja_pct: 20,
      n_ofertas_recibidas: 3,
    },
  ],
  total: 1,
  limit: 5,
  offset: 0,
};

describe("company profile presentation helpers", () => {
  it("opens the complete history unless a global date range is active", () => {
    expect(initialCompanyProfilePeriod(false)).toBe("all");
    expect(initialCompanyProfilePeriod(true)).toBe("global");
  });

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

  it("restores operational KPIs, yearly progress and recent awards in the company quick view", () => {
    render(
      <CompanyQuickView
        empresaId={7}
        company={{
          nombre: "Ejemplo Digital",
          nif: "B12345678", // pragma: allowlist secret
          count: 4,
          importe: 500000,
          cuota: 8,
          baja_media: 12,
          ofertas_medias: 2.5,
        }}
        profile={{
          ...profile,
          por_anio: [
            { anio: 2024, contratos: 3, importe: 400000 },
            { anio: 2025, contratos: 4, importe: 500000 },
          ],
        }}
        recentAwards={recentAwards}
        isLoadingProfile={false}
        isLoadingAwards={false}
        watched={false}
        watchPending={false}
        onToggleWatch={vi.fn()}
      />,
    );

    expect(screen.getByText("Operativa en cifras")).toBeInTheDocument();
    expect(screen.getByText("Baja media")).toBeInTheDocument();
    expect(screen.getByText("Progreso anual")).toBeInTheDocument();
    expect(screen.getByText("Adjudicaciones recientes")).toBeInTheDocument();
    expect(screen.getByText("Servicio de soporte y evolución de sistemas")).toBeInTheDocument();
  });
});
