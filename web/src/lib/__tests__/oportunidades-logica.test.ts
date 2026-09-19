/**
 * Lógica de presentación de F3.1, F4.1, F4.3 y F4.4: lo que se decide antes
 * de pintar. Todo es función pura, así que se prueba sin montar componentes.
 */
import { describe, expect, it } from "vitest";
import type { PursuitMetrics, Schemas } from "@/lib/api-types";
import {
  MOTIVOS_PERDIDA,
  errorDeCierre,
  esMotivoPerdida,
  etiquetaMotivo,
  pideCodificar,
  repartoPerdidas,
} from "@/lib/motivos-perdida";
import { fechaCorta, textoAdjudicacion } from "@/lib/adjudicacion-prevista";
import {
  filtrarCartera,
  opcionesCartera,
  origenFin,
  plazoRestante,
  urgenciaCartera,
} from "@/lib/cartera";
import { etiquetaTrimestre, previsionOrdenada, supuestosEtapas } from "@/lib/pipeline-ponderado";

const METRICS: PursuitMetrics = {
  organization_id: 1,
  awarded_amount_eur: 0,
  perdidas_n_minimo: 5,
  pipeline_sin_importe: 0,
  pipeline_value_eur: 0,
  pursuits_identified: 10,
  pursuits_lost: 3,
  pursuits_submitted: 4,
  pursuits_won: 1,
  unidad_de_conteo: "oportunidad",
};

describe("F3.1 — motivos de pérdida", () => {
  it("ofrece los siete códigos de D37 y no `sin_codificar`", () => {
    expect(MOTIVOS_PERDIDA.map((m) => m.codigo)).toEqual([
      "precio",
      "tecnica",
      "solvencia",
      "plazo",
      "desierto_o_anulado",
      "no_presentada",
      "otro",
    ]);
    expect(esMotivoPerdida("sin_codificar")).toBe(false);
    expect(etiquetaMotivo("sin_codificar")).toBe("Sin codificar");
    expect(etiquetaMotivo("precio")).toBe("Precio");
  });

  it("cerrar como perdida sin código es un error; otros resultados no lo piden", () => {
    expect(errorDeCierre("lost", "", "")).toMatch(/obligatorio/);
    expect(errorDeCierre("won", "", "")).toBeNull();
    expect(errorDeCierre("lost", "precio", "")).toBeNull();
  });

  it("«otro» exige texto: sin él es un cierre sin motivo con otra etiqueta", () => {
    expect(errorDeCierre("lost", "otro", "  ")).toMatch(/Otro/);
    expect(errorDeCierre("lost", "otro", "Cambio de alcance")).toBeNull();
  });

  it("ofrece completar los cierres perdidos sin código (backfill)", () => {
    expect(pideCodificar({ outcome: "lost", outcome_reason_code: null })).toBe(true);
    expect(pideCodificar({ outcome: "lost", outcome_reason_code: "precio" })).toBe(false);
    expect(pideCodificar({ outcome: "won" })).toBe(false);
  });

  it("por debajo del mínimo dice cuántas hay en vez de pintar porcentajes", () => {
    expect(repartoPerdidas(METRICS)).toEqual({ estado: "insuficiente", perdidas: 3, minimo: 5 });
    const filas = [{ motivo: "precio", n: 4, pct: 0.8 }, { motivo: "sin_codificar", n: 1, pct: 0.2 }];
    expect(repartoPerdidas({ ...METRICS, perdidas_por_motivo: filas })).toEqual({
      estado: "publicable",
      filas,
    });
  });
});

describe("F4.1 — valor ponderado", () => {
  it("ordena los supuestos por etapa del workflow", () => {
    const supuestos = supuestosEtapas({
      ...METRICS,
      probabilidades_etapa_usadas: { submitted: 60, identified: 10, preparing: 50 },
    });
    expect(supuestos.map((s) => [s.etapa, s.probabilidad])).toEqual([
      ["identified", 10],
      ["preparing", 50],
      ["submitted", 60],
    ]);
  });

  it("ordena la previsión cronológicamente y etiqueta los trimestres", () => {
    const prevision = previsionOrdenada({
      ...METRICS,
      prevision_trimestral: { "2027-Q1": 5, "2026-Q4": 10 },
    });
    expect(prevision.map((t) => t.etiqueta)).toEqual(["T4 2026", "T1 2027"]);
    expect(etiquetaTrimestre("raro")).toBe("raro");
  });
});

describe("F4.4 — fecha prevista de adjudicación", () => {
  it("sin estimación lo dice, sin fecha inventada", () => {
    const texto = textoAdjudicacion(null);
    expect(texto.valor).toBe("Sin estimación");
    expect(texto.metodo).toBeNull();
  });

  it("una estimación se presenta como intervalo con su base", () => {
    const texto = textoAdjudicacion({
      fecha: "2026-11-15",
      p25: "2026-11-01",
      p75: "2026-12-01",
      n: 12,
      metodo: "estimacion",
    });
    expect(texto.valor).toBe(`${fechaCorta("2026-11-01")} – ${fechaCorta("2026-12-01")}`);
    expect(texto.base).toContain("12 adjudicaciones");
    expect(texto.metodo).toBe("estimacion");
  });

  it("un hito publicado se presenta como fecha", () => {
    const texto = textoAdjudicacion({
      fecha: "2026-11-15",
      p25: "2026-11-15",
      p75: "2026-11-15",
      n: 0,
      metodo: "hito",
    });
    expect(texto.valor).toBe(fechaCorta("2026-11-15"));
    expect(texto.metodo).toBe("hito");
  });
});

describe("F4.3 — cartera", () => {
  const base: Schemas["ContratoCartera"] = {
    id: 1,
    organization_id: 1,
    pursuit_id: 1,
    licitacion_id: "L1",
    prorrogas_aplicadas: 0,
  };
  const contratos = [
    { ...base, id: 1, tecnologia: "SAP,Oracle", organo_contratacion: "Ayto. B", meses_restantes: 4 },
    { ...base, id: 2, tecnologia: "SAP", organo_contratacion: "Ayto. A", meses_restantes: 12 },
    { ...base, id: 3, tecnologia: null, organo_contratacion: null, meses_restantes: null },
  ];

  it("saca las opciones de filtro del CSV de tecnologías, ordenadas", () => {
    expect(opcionesCartera(contratos)).toEqual({
      tecnologias: ["Oracle", "SAP"],
      organos: ["Ayto. A", "Ayto. B"],
    });
  });

  it("filtra por tecnología dentro del CSV y por órgano", () => {
    expect(filtrarCartera(contratos, { tecnologia: "Oracle", organo: null }).map((c) => c.id)).toEqual([1]);
    expect(filtrarCartera(contratos, { tecnologia: "SAP", organo: "Ayto. A" }).map((c) => c.id)).toEqual([2]);
    expect(filtrarCartera(contratos, { tecnologia: null, organo: null })).toHaveLength(3);
  });

  it("sin fecha de fin lo dice, sin inventar plazo", () => {
    expect(plazoRestante(contratos[2])).toBe("Sin fecha de fin");
    expect(urgenciaCartera(contratos[2])).toBe("sin_fecha");
    expect(plazoRestante(contratos[0])).toBe("Vence en 4 meses");
    expect(urgenciaCartera(contratos[0])).toBe("pronto");
    expect(urgenciaCartera({ ...base, meses_restantes: -1 })).toBe("vencido");
  });

  it("declara de dónde sale la fecha de fin", () => {
    expect(origenFin("duracion")?.texto).toBe("estimada");
    expect(origenFin("prorroga")?.texto).toBe("con prórroga");
    expect(origenFin(null)).toBeNull();
  });
});
