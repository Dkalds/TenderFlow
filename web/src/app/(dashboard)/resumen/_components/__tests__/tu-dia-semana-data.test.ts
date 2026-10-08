import { describe, expect, it } from "vitest";
import { semanaEnCarriles } from "../tu-dia-semana-data";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";

function item(id: string, urgencia: PipelineAgendaItem["urgencia"], dias: number | null): PipelineAgendaItem {
  return {
    kind: "pursuit",
    urgencia,
    dias_restantes: dias,
    licitacion_id: id,
    titulo: id,
  } as PipelineAgendaItem;
}

// Jueves 8 de octubre de 2026.
const hoy = new Date(2026, 9, 8, 12, 0);

describe("semanaEnCarriles", () => {
  it("pone lo vencido delante, hoy siempre, y un carril por día con algo", () => {
    const tramos = semanaEnCarriles(
      [item("V", "vencida", -1), item("H", "hoy", 0), item("D1", "semana", 1), item("D4", "semana", 4)],
      hoy,
    );
    expect(tramos.map((t) => (t.tipo === "carril" ? t.etiqueta : `libre:${t.etiqueta}`))).toEqual([
      "Vencido",
      "Hoy",
      "vie 9",
      "libre:sáb 10 – dom 11",
      "lun 12",
      "libre:mar 13 – jue 15",
    ]);
  });

  it("conserva el orden del backend dentro de cada carril", () => {
    const tramos = semanaEnCarriles([item("B", "hoy", 0), item("A", "hoy", 0)], hoy);
    const hoyCarril = tramos.find((t) => t.tipo === "carril" && t.etiqueta === "Hoy");
    expect(hoyCarril?.tipo === "carril" && hoyCarril.items.map((i) => i.licitacion_id)).toEqual(["B", "A"]);
  });

  it("sin vencidos no hay carril de vencido, y una semana vacía es un solo hueco", () => {
    const tramos = semanaEnCarriles([], hoy);
    expect(tramos).toHaveLength(2);
    expect(tramos[0]).toMatchObject({ tipo: "carril", etiqueta: "Hoy", items: [] });
    expect(tramos[1]).toMatchObject({ tipo: "libre", etiqueta: "vie 9 – jue 15" });
  });

  it("deja fuera lo que no vence esta semana", () => {
    const tramos = semanaEnCarriles([item("M", "mes", 12), item("S", "sin_fecha", null)], hoy);
    expect(tramos.flatMap((t) => (t.tipo === "carril" ? t.items : []))).toHaveLength(0);
  });
});
