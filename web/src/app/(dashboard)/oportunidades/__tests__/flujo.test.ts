import { describe, expect, it } from "vitest";
import {
  CERRADA_NO_CAMBIA,
  bloqueoDeFase,
  decisionesPermitidas,
  motivoBloqueo,
  resultadosPermitidos,
  siguienteFase,
  type EstadoFlujo,
} from "../_lib/flujo";

/**
 * El espejo de `_TRANSITIONS` y de las reglas de decisión de
 * `services/pursuits.py`. Si uno de estos casos cambia, cambió el backend: hay
 * que mirar allí antes de tocar el test.
 */
const en = (status: EstadoFlujo["status"], decision: EstadoFlujo["decision"] = "pending"): EstadoFlujo => ({
  status,
  decision,
});

describe("flujo de una oportunidad", () => {
  it("avanza de fase en fase hasta Presentada, y de ahí solo se cierra", () => {
    expect(siguienteFase("identified")).toBe("qualifying");
    expect(siguienteFase("qualifying")).toBe("go_no_go");
    expect(siguienteFase("go_no_go")).toBe("preparing");
    expect(siguienteFase("preparing")).toBe("submitted");
    expect(siguienteFase("submitted")).toBeNull();
    expect(siguienteFase("won")).toBeNull();
  });

  it("acepta el paso siguiente y quedarse donde está", () => {
    expect(motivoBloqueo(en("identified"), "qualifying")).toBeNull();
    expect(motivoBloqueo(en("qualifying"), "qualifying")).toBeNull();
  });

  it("no deja saltar fases ni volver atrás, y dice cuál es el paso posible", () => {
    expect(motivoBloqueo(en("identified"), "submitted")).toBe(
      "Desde «Identificada» solo se avanza a «En cualificación» o se retira.",
    );
    expect(motivoBloqueo(en("preparing", "go"), "qualifying")).toMatch(/solo se avanza a «Presentada»/);
    expect(motivoBloqueo(en("submitted", "go"), "preparing")).toBe(
      "Desde «Presentada» solo se registra el resultado o se retira.",
    );
  });

  it("no deja preparar oferta sin la decisión GO", () => {
    expect(motivoBloqueo(en("go_no_go"), "preparing")).toBe(
      "Preparar o presentar una oferta exige la decisión GO.",
    );
    expect(motivoBloqueo(en("go_no_go", "no_go"), "preparing")).not.toBeNull();
    expect(motivoBloqueo(en("go_no_go", "go"), "preparing")).toBeNull();
  });

  it("con NO-GO solo cabe retirarla", () => {
    expect(motivoBloqueo(en("go_no_go", "no_go"), "withdrawn")).toBeNull();
    expect(resultadosPermitidos(en("go_no_go", "no_go"))).toEqual(["withdrawn"]);
  });

  it("una oportunidad cerrada ya no cambia", () => {
    expect(motivoBloqueo(en("won", "go"), "submitted")).toBe(CERRADA_NO_CAMBIA);
    expect(resultadosPermitidos(en("lost", "go"))).toEqual([]);
    expect(bloqueoDeFase(en("withdrawn"), "cerrada")).toBe(CERRADA_NO_CAMBIA);
  });

  it("solo desde Presentada se gana o se pierde; antes, cerrar es retirarla", () => {
    expect(resultadosPermitidos(en("submitted", "go"))).toEqual(["won", "lost", "withdrawn"]);
    expect(resultadosPermitidos(en("preparing", "go"))).toEqual(["withdrawn"]);
    expect(resultadosPermitidos(en("identified"))).toEqual(["withdrawn"]);
  });

  it("traduce las columnas del tablero: Cerradas acepta mientras quede un resultado", () => {
    expect(bloqueoDeFase(en("identified"), "cerrada")).toBeNull();
    expect(bloqueoDeFase(en("identified"), "qualifying")).toBeNull();
    expect(bloqueoDeFase(en("identified"), "go_no_go")).not.toBeNull();
  });

  it("solo ofrece las decisiones que el PATCH acepta sin mover la fase", () => {
    // El NO-GO solo cabe en «Decisión» o en una retirada…
    expect(decisionesPermitidas(en("identified"))).toEqual(["pending", "go"]);
    expect(decisionesPermitidas(en("qualifying"))).toEqual(["pending", "go"]);
    expect(decisionesPermitidas(en("go_no_go"))).toEqual(["pending", "go", "no_go"]);
    expect(decisionesPermitidas(en("withdrawn"))).toEqual(["pending", "go", "no_go"]);
    // …y con la oferta en marcha, o cerrada con resultado, la decisión es GO.
    for (const status of ["preparing", "submitted", "won", "lost"] as const) {
      expect(decisionesPermitidas(en(status, "go"))).toEqual(["go"]);
    }
  });
});
