import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { FichaModificaciones } from "@/components/ficha/ficha-modificaciones";
import type { ModificacionPublicada, ModificacionesDeLicitacion } from "@/lib/api-types";
import type { LicitacionDetail } from "@/lib/licitacion-detail";

const base: LicitacionDetail = {
  id_externo: "placsp:ORG1:B070005/2022-0071",
  titulo: "Mantenimiento de las aplicaciones municipales",
  organo_contratacion: "Ayuntamiento de Pruebas",
  importe: 377601.78,
  estado: "RES",
  fecha_publicacion: "2023-01-10",
  ccaa: "Illes Balears",
  cpv: "72267100",
  url: null,
  fuente: "placsp",
  tecnologia: null,
  tipo_contrato: "2",
  provincia: null,
  fecha_limite: null,
  fecha_inicio: null,
  fecha_fin: null,
  descripcion: null,
};

const vacia: ModificacionPublicada = {
  fuente: "placsp",
  numero: null,
  lote_numero: null,
  fecha_publicacion: null,
  motivo_codigo: null,
  motivo: null,
  descripcion: null,
  importe_modificacion: null,
  importe_modificacion_base: null,
  importe_final: null,
  importe_final_base: null,
  importe_aviso: null,
  importe_aviso_base: null,
  moneda: null,
  plazo_modificacion: null,
  plazo_final: null,
  plazo_unidad: null,
  aviso_original: null,
  url: null,
};

function ficha(modificaciones: ModificacionesDeLicitacion) {
  return render(<FichaModificaciones licitacion={{ ...base, modificaciones }} />);
}

afterEach(cleanup);

// CU-38: lo que un contrato ha acabado costando y si su órgano suele ampliarlos.

describe("FichaModificaciones", () => {
  it("enseña cada modificación, el coste tras ellas y lo que falta como no publicado", () => {
    ficha({
      items: [
        {
          ...vacia,
          numero: "1",
          lote_numero: "1",
          motivo: "1ª Prórroga prevista en el contrato",
          importe_modificacion: 188800.89,
          importe_modificacion_base: "sin_iva",
          importe_final: 377601.79,
          importe_final_base: "sin_iva",
          plazo_modificacion: 1,
          plazo_final: 2,
          plazo_unidad: "ANN",
        },
        { ...vacia, numero: "2", lote_numero: "1", importe_final: 566402.68, importe_final_base: "sin_iva" },
      ],
      costes: [{ lote_numero: "1", adjudicado: 188800.89, final: 566402.68, variacion_pct: 200, base: "sin_iva" }],
      organo: { n: 1, muestra_minima: 10, mediana_pct: null, base: "sin_iva" },
    });

    expect(screen.getByRole("heading", { name: "Modificaciones del contrato" })).toBeInTheDocument();
    expect(screen.getByText("1ª Prórroga prevista en el contrato")).toBeInTheDocument();
    expect(screen.getAllByText(/fecha no publicada/)).toHaveLength(2);
    expect(screen.getByText("Motivo no publicado")).toBeInTheDocument();
    expect(screen.getByText("Lote 1: tras modificaciones")).toBeInTheDocument();
    expect(screen.getByText("+200,0%")).toBeInTheDocument();
    // Por debajo de la muestra del órgano no hay cifra, sí el N.
    expect(screen.getByText(/Sin datos suficientes: 1 contrato suyo tiene/)).toBeInTheDocument();
  });

  it("un aviso de TED enseña su motivo de eForms y enlaza al aviso", () => {
    ficha({
      items: [
        {
          ...vacia,
          fuente: "ted",
          fecha_publicacion: "2026-10-01",
          motivo_codigo: "add-wss",
          motivo: "Necesidad de servicios adicionales",
          importe_aviso: 320477,
          importe_aviso_base: "desconocido",
          url: "https://ted.europa.eu/es/notice/800001-2026/pdf",
        },
      ],
      costes: [],
      organo: { n: 12, muestra_minima: 10, mediana_pct: 14.5, base: "sin_iva" },
    });

    expect(screen.getByText("Obras, servicios o suministros adicionales")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver el aviso" })).toHaveAttribute(
      "href",
      "https://ted.europa.eu/es/notice/800001-2026/pdf",
    );
    expect(screen.getByText(/fuente: TED/)).toBeInTheDocument();
    // BT-720 no se rotula como importe final: no se sabe si es antes o después.
    expect(screen.getByText(/valor publicado en el aviso 320\.477/)).toBeInTheDocument();
    expect(screen.queryByText(/importe tras ella/)).not.toBeInTheDocument();
    expect(screen.getByText("+14,5%")).toBeInTheDocument();
    expect(screen.getByText(/Mediana entre 12 contratos modificados/)).toBeInTheDocument();
  });

  it("sin modificaciones ni dato del órgano no pinta nada", () => {
    const { container } = ficha({
      items: [],
      costes: [],
      organo: { n: 0, muestra_minima: 10, mediana_pct: null, base: "sin_iva" },
    });

    expect(container).toBeEmptyDOMElement();
  });
});
