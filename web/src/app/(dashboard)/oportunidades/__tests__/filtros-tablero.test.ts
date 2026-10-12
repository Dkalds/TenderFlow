import { describe, expect, it } from "vitest";
import { TODAS_LAS_ETIQUETAS } from "@/components/etiquetas/filtro-etiqueta";
import {
  FILTROS_VACIOS,
  TODOS_LOS_RESPONSABLES,
  TOPE_TABLERO,
  consultaDelTablero,
  hayFiltros,
} from "../_lib/filtros-tablero";

describe("filtros del tablero", () => {
  it("sin filtros pide la página entera del tablero y nada más", () => {
    expect(hayFiltros(FILTROS_VACIOS)).toBe(false);
    expect(consultaDelTablero(FILTROS_VACIOS)).toEqual({ limit: TOPE_TABLERO });
  });

  it("traduce cada control a su parámetro de `GET /pursuits`", () => {
    const filtros = { q: "  nóminas ", etiqueta: "4", responsable: "9", plazo: "7d" as const };
    expect(hayFiltros(filtros)).toBe(true);
    expect(consultaDelTablero(filtros)).toEqual({
      limit: TOPE_TABLERO,
      q: "nóminas",
      etiqueta: 4,
      responsible_user_id: 9,
      plazo: "7d",
    });
  });

  it("un texto de espacios no es un filtro", () => {
    const filtros = { ...FILTROS_VACIOS, q: "   " };
    expect(hayFiltros(filtros)).toBe(false);
    expect(consultaDelTablero(filtros)).toEqual({ limit: TOPE_TABLERO });
  });

  it("los valores «todos» no viajan", () => {
    const filtros = {
      q: "",
      etiqueta: TODAS_LAS_ETIQUETAS,
      responsable: TODOS_LOS_RESPONSABLES,
      plazo: "todos" as const,
    };
    expect(consultaDelTablero(filtros)).toEqual({ limit: TOPE_TABLERO });
  });
});
