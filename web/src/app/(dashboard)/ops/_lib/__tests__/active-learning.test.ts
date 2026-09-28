/**
 * La selección de familias y fabricantes del formulario de revisión (spec
 * §3.3): una lista ordenada por expediente, cuya primera etiqueta es la
 * principal (`tecnologia`) y el resto las secundarias.
 */
import { describe, expect, it } from "vitest";
import { alternarEtiqueta, hacerPrincipal, seleccionInicial, type QueueItem } from "../active-learning";

const ITEM: QueueItem = {
  id_externo: "EXP-1",
  llm: { es_ti: true, confianza_es_ti: 0.9, familias: ["DESARROLLO", "SAP"], sin_evidencia: false },
};

describe("seleccionInicial", () => {
  it("arranca con la propuesta del LLM, en su orden", () => {
    expect(seleccionInicial(ITEM)).toEqual(["DESARROLLO", "SAP"]);
  });

  it("sin propuesta arranca vacía", () => {
    expect(seleccionInicial({ id_externo: "EXP-2", llm: null })).toEqual([]);
    expect(seleccionInicial(undefined)).toEqual([]);
  });

  it("no comparte la lista de la propuesta: editarla no la toca", () => {
    const seleccion = seleccionInicial(ITEM);
    seleccion.push("ERP");
    expect(ITEM.llm?.familias).toEqual(["DESARROLLO", "SAP"]);
  });
});

describe("alternarEtiqueta", () => {
  it("añade al final una etiqueta que no estaba", () => {
    expect(alternarEtiqueta(["DESARROLLO"], "CLOUD_INFRA")).toEqual(["DESARROLLO", "CLOUD_INFRA"]);
  });

  it("quita una que estaba; si era la principal, la siguiente pasa a serlo", () => {
    expect(alternarEtiqueta(["DESARROLLO", "SAP"], "DESARROLLO")).toEqual(["SAP"]);
  });

  it("en una selección vacía, la primera que se marca es la principal", () => {
    expect(alternarEtiqueta([], "GIS")).toEqual(["GIS"]);
  });
});

describe("hacerPrincipal", () => {
  it("pone la etiqueta delante sin perder las demás", () => {
    expect(hacerPrincipal(["DESARROLLO", "SAP"], "SAP")).toEqual(["SAP", "DESARROLLO"]);
    expect(hacerPrincipal(["DESARROLLO"], "ERP")).toEqual(["ERP", "DESARROLLO"]);
  });

  it("sobre la que ya era principal, la quita", () => {
    expect(hacerPrincipal(["DESARROLLO", "SAP"], "DESARROLLO")).toEqual(["SAP"]);
  });
});
