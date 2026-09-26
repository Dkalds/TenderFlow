/**
 * El expediente dentro de la ficha: los datos se leen en castellano.
 *
 * Los bloques compartidos con el inspector de Detalle tienen sus propios tests;
 * aquí se doblan y se fija lo que es de este panel: el tipo de contrato con su
 * etiqueta y no el código CODICE, el importe con el mismo nombre que en el
 * Resumen, y fuera la «descripción» que solo repite metadatos.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const h = vi.hoisted(() => ({ licitacion: {} as Record<string, unknown> }));

vi.mock("@/hooks/use-licitacion", () => ({
  useLicitacion: () => ({ data: h.licitacion, isLoading: false, error: null, refetch: vi.fn() }),
}));
vi.mock("@/hooks/use-meta-filters", () => ({
  useMetaFilters: () => ({
    data: { tipo_contrato: [{ codigo: "1", etiqueta: "Suministros", descripcion: "Contrato de suministro" }] },
  }),
}));
vi.mock("@/components/documentos-block", () => ({ DocumentosBlock: () => null }));
vi.mock("@/components/eventos-timeline", () => ({ EventosTimeline: () => null }));
vi.mock("@/components/resoluciones-block", () => ({ ResolucionesBlock: () => null }));
vi.mock("@/components/tecnologias-block", () => ({ TecnologiasBlock: () => null }));
vi.mock("@/components/competitors/socios-ute", () => ({ SociosUte: () => null }));
vi.mock("@/components/ui/glosario-hint", () => ({ GlosarioHint: () => null }));

import { ExpedientePanel } from "@/components/pursuits/expediente-panel";

beforeEach(() => {
  h.licitacion = {
    id_externo: "0596/2026",
    titulo: "Licencias SAP Analytics Cloud",
    organo_contratacion: "EMASESA",
    importe: 188_131,
    tipo_contrato: "1",
    estado: null,
    descripcion: null,
  };
});

describe("ExpedientePanel", () => {
  it("el tipo de contrato sale con su etiqueta del catálogo, no con el código", () => {
    render(<ExpedientePanel licitacionId="0596/2026" />);
    expect(screen.getByText("Suministros")).toBeInTheDocument();
  });

  it("el importe se llama como en el Resumen", () => {
    render(<ExpedientePanel licitacionId="0596/2026" />);
    expect(screen.getByText("Importe de licitación")).toBeInTheDocument();
  });

  it("omite la descripción que solo repite los metadatos del anuncio", () => {
    h.licitacion.descripcion =
      "Id licitación: 0596/2026; Órgano de Contratación: EMASESA; Importe: 188131.15 EUR; Estado: PUB";
    render(<ExpedientePanel licitacionId="0596/2026" />);
    expect(screen.queryByText("Descripción")).not.toBeInTheDocument();
    expect(screen.queryByText(/Estado: PUB/)).not.toBeInTheDocument();
  });

  it("una descripción de verdad sí se enseña", () => {
    h.licitacion.descripcion = "Suscripción de 40 licencias de SAP Analytics Cloud durante dos años.";
    render(<ExpedientePanel licitacionId="0596/2026" />);
    expect(screen.getByText("Descripción")).toBeInTheDocument();
    expect(screen.getByText(/40 licencias/)).toBeInTheDocument();
  });
});
