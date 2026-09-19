import { describe, expect, it } from "vitest";
import type { Pursuit } from "@/hooks/use-pursuits";
import { salidaDeFase } from "../_lib/salida-fase";

const base = {
  id: 9,
  organization_id: 7,
  licitacion_id: "2026/0410",
  status: "go_no_go",
  decision: "pending",
  outcome: "pending",
  version: 3,
  responsible_user_id: null,
  next_action: null,
  decision_reason: null,
  offer_price_eur: null,
  awarded_amount_eur: null,
  outcome_reason: null,
  outcome_reason_code: null,
  adjudicacion: null,
} as unknown as Pursuit;

const en = (cambios: Partial<Pursuit>): Pursuit => ({ ...base, ...cambios }) as Pursuit;

const paso = (salida: ReturnType<typeof salidaDeFase>, clave: string) =>
  salida.pasos.find((candidato) => candidato.clave === clave);

describe("salidaDeFase", () => {
  it("nombra la fase de la que hay que salir y cuenta solo lo que hay hecho", () => {
    const salida = salidaDeFase(en({ status: "identified", responsible_user_id: 4 }));
    expect(salida.titulo).toBe("Para salir de «Identificada»");
    expect(salida.pasos.map((paso) => paso.clave)).toEqual(["responsable", "plazo", "proxima"]);
    expect(salida.hechos).toBe(1);
    expect(salida.accion).toEqual({
      tipo: "avanzar",
      destino: "qualifying",
      etiqueta: "Empezar a cualificar",
      bloqueo: null,
    });
  });

  it("bloquea empezar la oferta mientras no haya GO, y dice por qué", () => {
    const salida = salidaDeFase(en({ status: "go_no_go" }));
    expect(paso(salida, "decision")).toMatchObject({ hecho: false, requerido: true });
    expect(salida.accion).toMatchObject({
      tipo: "avanzar",
      destino: "preparing",
      bloqueo: "Preparar o presentar una oferta exige la decisión GO.",
    });
  });

  it("con el GO y su motivo, deja avanzar", () => {
    const salida = salidaDeFase(
      en({ status: "go_no_go", decision: "go", decision_reason: "Encaja", offer_price_eur: 2_080_000 }),
    );
    expect(salida.hechos).toBe(3);
    expect(salida.accion).toMatchObject({ tipo: "avanzar", bloqueo: null });
  });

  it("con el NO-GO, la salida es retirarla", () => {
    const salida = salidaDeFase(en({ status: "go_no_go", decision: "no_go", decision_reason: "Sin solvencia" }));
    expect(salida.accion).toEqual({ tipo: "cerrar", etiqueta: "Retirar la oportunidad" });
    expect(salida.hechos).toBe(2);
  });

  it("desde Presentada la salida es registrar el resultado", () => {
    const salida = salidaDeFase(en({ status: "submitted", decision: "go" }));
    expect(salida.accion).toEqual({ tipo: "cerrar", etiqueta: "Registrar resultado" });
  });

  it("no da por pendiente lo que todavía no sabe", () => {
    // Sin kit cargado, el paso no es «no»: es «no se sabe», y no cuenta.
    const sinKit = salidaDeFase(en({ status: "preparing", decision: "go" }));
    expect(paso(sinKit, "kit")?.hecho).toBeNull();
    expect(sinKit.hechos).toBe(0);

    const conKit = salidaDeFase(en({ status: "preparing", decision: "go" }), {
      kit: { listos: 2, total: 3 },
    });
    expect(paso(conKit, "kit")).toMatchObject({ hecho: false, detalle: "2 de 3 listos" });

    const kitCompleto = salidaDeFase(en({ status: "preparing", decision: "go" }), {
      kit: { listos: 3, total: 3 },
    });
    expect(paso(kitCompleto, "kit")?.hecho).toBe(true);
  });

  it("un pliego sin requisitos extraídos no se cuenta como contraste pendiente", () => {
    const vacio = salidaDeFase(en({ status: "qualifying" }), {
      contraste: { total_requisitos: 0, desconocido: 0 },
    });
    expect(paso(vacio, "contraste")).toMatchObject({
      hecho: null,
      detalle: "El pliego no tiene requisitos extraídos",
    });

    const conDudas = salidaDeFase(en({ status: "qualifying" }), {
      contraste: { total_requisitos: 12, desconocido: 3 },
    });
    expect(paso(conDudas, "contraste")).toMatchObject({
      hecho: false,
      detalle: "3 de 12 sin contrastar",
    });
  });

  it("arrastra los huecos de las fases anteriores, diciendo de dónde vienen", () => {
    const salida = salidaDeFase(
      en({ status: "preparing", decision: "go", decision_reason: "Encaja", offer_price_eur: 2_000_000 }),
      { kit: { listos: 3, total: 3 } },
    );
    // Lo suyo primero; detrás, lo que quedó sin hacer por el camino.
    expect(salida.pasos.slice(0, 2).map((p) => p.clave)).toEqual(["kit", "oferta"]);
    expect(paso(salida, "responsable")).toMatchObject({
      hecho: false,
      detalle: "Quedó pendiente en «Identificada»",
    });
    // El precio ya está en la lista de la fase: no se repite con otro nombre.
    expect(salida.pasos.filter((p) => p.clave === "oferta")).toHaveLength(1);
    // Un paso sin dato no es deuda: el contraste del pliego no se arrastra.
    expect(paso(salida, "contraste")).toBeUndefined();
  });

  it("de una cerrada enseña lo que quedó registrado, sin acción que ofrecer", () => {
    const ganada = salidaDeFase(
      en({ status: "won", decision: "go", outcome: "won", awarded_amount_eur: 2_000_000 }),
    );
    expect(ganada.titulo).toBe("Lo que quedó registrado al cerrar");
    expect(ganada.accion).toBeNull();
    expect(paso(ganada, "resultado")?.texto).toBe("Resultado registrado: Ganada");
    expect(paso(ganada, "importe")?.hecho).toBe(true);
    expect(paso(ganada, "motivo")?.hecho).toBe(false);

    // El importe solo se exige en las ganadas: en una pérdida es de otro, y
    // retirarla no adjudica nada.
    const perdida = salidaDeFase(en({ status: "lost", decision: "go", outcome: "lost" }));
    expect(paso(perdida, "importe")).toBeUndefined();
    const retirada = salidaDeFase(en({ status: "withdrawn", outcome: "cancelled" }));
    expect(paso(retirada, "importe")).toBeUndefined();
  });
});
