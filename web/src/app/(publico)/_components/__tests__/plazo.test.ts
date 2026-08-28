import { describe, expect, it } from "vitest";

import { plazoPresentacion } from "../plazo";

/**
 * Lo que fijan estos tests es el veredicto, no el formato.
 *
 * El riesgo que cubren es asimétrico: anunciar como abierto un plazo cerrado
 * manda a alguien a preparar una oferta imposible, y anunciar como cerrado uno
 * que sigue vivo le quita una oportunidad real. Por eso hay un caso por cada
 * lado de la medianoche española y uno para el valor que no se puede
 * interpretar, donde la respuesta correcta es callarse y no cerrar nada.
 */
describe("plazoPresentacion", () => {
  const HOY = new Date("2026-08-28T10:00:00+02:00");

  it("no inventa plazo si el anuncio no trae fecha límite", () => {
    expect(plazoPresentacion(null, HOY)).toBeNull();
    expect(plazoPresentacion(undefined, HOY)).toBeNull();
    expect(plazoPresentacion("", HOY)).toBeNull();
  });

  it("da por abierto lo que vence más adelante", () => {
    expect(plazoPresentacion("2026-12-31", HOY)).toEqual({ fecha: "31 dic 2026", vencido: false });
  });

  it("da por cerrado lo que venció", () => {
    expect(plazoPresentacion("2026-03-03", HOY)).toEqual({ fecha: "3 mar 2026", vencido: true });
  });

  it("mantiene abierto el plazo que vence hoy", () => {
    // El día de cierre todavía se puede presentar oferta, y con ISR el
    // veredicto se hornea hasta una hora antes de que nadie lo lea.
    expect(plazoPresentacion("2026-08-28", HOY)).toEqual({ fecha: "28 ago 2026", vencido: false });
  });

  it("resuelve la medianoche en la zona española, no en el UTC del runtime", () => {
    // 00:30 en Madrid es todavía el 27 en UTC. Si la comparación usara la zona
    // del runtime de Next, un plazo que cerró el 27 seguiría anunciándose vivo.
    const madrugada = new Date("2026-08-28T00:30:00+02:00");

    expect(plazoPresentacion("2026-08-27", madrugada)?.vencido).toBe(true);
    expect(plazoPresentacion("2026-08-28", madrugada)?.vencido).toBe(false);
  });

  it("entiende el formato heredado DD/MM/YYYY de las filas antiguas", () => {
    expect(plazoPresentacion("03/03/2026", HOY)).toEqual({ fecha: "3 mar 2026", vencido: true });
  });

  it("ante un valor ilegible no declara cerrado nada", () => {
    expect(plazoPresentacion("pendiente", HOY)).toEqual({ fecha: "pendiente", vencido: false });
  });
});
