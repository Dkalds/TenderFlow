/**
 * Las fechas de la ficha: duración de la ejecución y calendario del expediente.
 *
 * Se fija con un «hoy» explícito porque lo que se pinta depende del día: un
 * test atado al reloj caducaría solo.
 */
import { describe, expect, it } from "vitest";
import { hitosDelExpediente, mesesDeEjecucion } from "@/components/ficha/ficha-fechas";

const HOY = new Date("2026-10-05T10:00:00Z");

describe("mesesDeEjecucion", () => {
  it("dice la duración en meses, redondeada", () => {
    expect(mesesDeEjecucion("2027-01-01", "2028-12-31")).toBe(24);
    expect(mesesDeEjecucion("2027-01-01", "2027-07-01")).toBe(6);
  });

  it("sin una de las dos fechas, o con el fin antes del inicio, no hay duración", () => {
    expect(mesesDeEjecucion(null, "2028-12-31")).toBeNull();
    expect(mesesDeEjecucion("2027-01-01", undefined)).toBeNull();
    expect(mesesDeEjecucion("no es fecha", "2028-12-31")).toBeNull();
    expect(mesesDeEjecucion("2028-12-31", "2027-01-01")).toBeNull();
  });
});

describe("hitosDelExpediente", () => {
  const completa = {
    fecha_publicacion: "2026-09-22",
    fecha_limite: "2026-10-13",
    fecha_inicio: "2027-01-01",
    fecha_fin: "2028-12-31",
  };

  it("coloca «hoy» entre las fechas, en orden cronológico", () => {
    const hitos = hitosDelExpediente(completa, HOY);
    expect(hitos.map((hito) => hito.clave)).toEqual(["publicacion", "hoy", "limite", "inicio", "fin"]);
    expect(hitos.map((hito) => hito.pasado)).toEqual([true, true, false, false, false]);
  });

  it("la fecha límite lleva su banda de urgencia y los días que quedan", () => {
    const limite = hitosDelExpediente(completa, HOY).find((hito) => hito.clave === "limite");
    expect(limite?.banda).toBe("medio");
    expect(limite?.plazo).toBe("8 d para cierre");
  });

  it("una fecha límite vencida queda detrás de «hoy» y lo dice", () => {
    const hitos = hitosDelExpediente({ ...completa, fecha_limite: "2026-10-01" }, HOY);
    expect(hitos.map((hito) => hito.clave)).toEqual(["publicacion", "limite", "hoy", "inicio", "fin"]);
    const limite = hitos.find((hito) => hito.clave === "limite");
    expect(limite?.banda).toBe("pasado");
    expect(limite?.plazo).toMatch(/^Vencida hace/);
  });

  it("no estima las fechas que faltan", () => {
    const hitos = hitosDelExpediente(
      { fecha_publicacion: "2026-09-22", fecha_limite: "2026-10-13", fecha_inicio: null, fecha_fin: null },
      HOY,
    );
    expect(hitos.map((hito) => hito.clave)).toEqual(["publicacion", "hoy", "limite"]);
  });

  it("con menos de dos fechas reales no hay calendario", () => {
    expect(
      hitosDelExpediente(
        { fecha_publicacion: "2026-09-22", fecha_limite: null, fecha_inicio: null, fecha_fin: null },
        HOY,
      ),
    ).toEqual([]);
  });
});
