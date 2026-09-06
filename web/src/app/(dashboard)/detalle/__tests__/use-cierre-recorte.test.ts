/**
 * Ventana de cierre: el recorte local de /detalle.
 *
 * Las dos funciones puras del hook — qué llega a la query y qué dice el chip.
 * Un valor ilegible se ignora en vez de viajar al backend, que respondería 422
 * y vaciaría la tabla entera.
 */
import { describe, it, expect } from "vitest";
import { cierreLabel, cierreParams } from "../_hooks/use-cierre-recorte";

/* ── ventana de cierre ──────────────────────────────────────────────── */

describe("cierreParams", () => {
  it("pasa las dos cotas con los nombres del contrato de la API", () => {
    expect(cierreParams("2026-08-26", "2026-08-27")).toEqual({
      cierre_desde: "2026-08-26",
      cierre_hasta: "2026-08-27",
    });
  });

  it("acepta una sola cota", () => {
    expect(cierreParams(null, "2026-08-27")).toEqual({ cierre_hasta: "2026-08-27" });
    expect(cierreParams("2026-08-26", null)).toEqual({ cierre_desde: "2026-08-26" });
  });

  it("descarta lo que no sea YYYY-MM-DD", () => {
    // El backend responde 422 a un formato inválido y un 422 vacía la tabla:
    // una URL editada a mano no puede tumbar la pantalla.
    expect(cierreParams("27/08/2026", "mañana")).toEqual({});
    expect(cierreParams(null, null)).toEqual({});
  });
});

describe("cierreLabel", () => {
  it("declara el recorte activo y devuelve null cuando no hay ninguno", () => {
    expect(cierreLabel({ cierre_desde: "2026-08-26", cierre_hasta: "2026-08-27" })).toBe(
      "Cierra 2026-08-26 → 2026-08-27",
    );
    expect(cierreLabel({ cierre_hasta: "2026-08-27" })).toBe("Cierra hasta 2026-08-27");
    expect(cierreLabel({ cierre_desde: "2026-08-26" })).toBe("Cierra desde 2026-08-26");
    expect(cierreLabel({})).toBeNull();
  });
});
