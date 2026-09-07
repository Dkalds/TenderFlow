import { describe, it, expect } from "vitest";
import { horasRestantes, proximasACerrar } from "@/app/(dashboard)/resumen/_components/cola-cierre";
import { esNueva } from "@/app/(dashboard)/resumen/_components/types";
import type { LicitacionSummary } from "@/lib/api-types";

const AHORA = Date.parse("2026-09-06T12:00:00Z");

function lic(id: string, limite: string | null, extra: Partial<LicitacionSummary> = {}) {
  return { id_externo: id, fecha_limite: limite, ...extra } as LicitacionSummary;
}

describe("horasRestantes", () => {
  it("redondea hacia abajo: un plazo que se agota no regala tiempo", () => {
    // 9 h 50 min son «9 h», no «10 h».
    expect(horasRestantes("2026-09-06T21:50:00Z", AHORA)).toBe(9);
  });

  it("nunca baja de cero aunque el cierre ya haya pasado", () => {
    expect(horasRestantes("2026-09-05T12:00:00Z", AHORA)).toBe(0);
  });

  it("se abstiene sin fecha o con fecha ilegible", () => {
    expect(horasRestantes(null, AHORA)).toBeNull();
    expect(horasRestantes(undefined, AHORA)).toBeNull();
    expect(horasRestantes("mañana por la tarde", AHORA)).toBeNull();
  });
});

describe("proximasACerrar", () => {
  it("ordena por plazo ascendente, no por el orden en que llegan", () => {
    // El endpoint ordena por fecha_publicacion y no acepta `fecha_limite` en
    // `sort`: si esto no ordenase, la tarjeta enseñaría cuatro cualesquiera.
    const filas = proximasACerrar(
      [
        lic("C", "2026-09-08T12:00:00Z"),
        lic("A", "2026-09-06T21:00:00Z"),
        lic("B", "2026-09-07T12:00:00Z"),
      ],
      AHORA,
    );
    expect(filas.map((f) => f.id)).toEqual(["A", "B", "C"]);
    expect(filas.map((f) => f.horas)).toEqual([9, 24, 48]);
  });

  it("descarta las que no traen fecha límite legible", () => {
    // Una fila sin plazo no puede ocupar sitio en una lista que ordena por
    // plazo: no se sabe dónde va.
    const filas = proximasACerrar([lic("SIN", null), lic("OK", "2026-09-07T12:00:00Z")], AHORA);
    expect(filas.map((f) => f.id)).toEqual(["OK"]);
  });

  it("recorta a las que caben", () => {
    const muchas = Array.from({ length: 9 }, (_, i) =>
      lic(`L${i}`, new Date(AHORA + (i + 1) * 3_600_000).toISOString()),
    );
    expect(proximasACerrar(muchas, AHORA)).toHaveLength(4);
    expect(proximasACerrar(muchas, AHORA, 2).map((f) => f.id)).toEqual(["L0", "L1"]);
  });

  it("cae a un guion cuando falta el órgano, y no a «undefined»", () => {
    const [fila] = proximasACerrar([lic("X", "2026-09-07T12:00:00Z")], AHORA);
    expect(fila.organo).toBe("—");
    expect(fila.titulo).toBe("X");
  });
});

describe("esNueva", () => {
  it("marca lo publicado en el corte o después", () => {
    const corte = "2026-09-01T10:00:00Z";
    expect(esNueva("2026-09-02T00:00:00Z", corte)).toBe(true);
    // El límite entra: el backend cuenta con `>=`, y marcar con `>` dejaría
    // fuera de la tabla una fila que el recuento sí incluyó.
    expect(esNueva(corte, corte)).toBe(true);
    expect(esNueva("2026-08-31T23:59:00Z", corte)).toBe(false);
  });

  it("sin corte no marca nada", () => {
    // Usuario sin `last_login`: el endpoint devuelve `desde: null` y la tabla
    // se queda sin marcas, que es la salida segura — marcar algunas y otras no
    // se leería como «éstas no son nuevas».
    expect(esNueva("2026-09-02T00:00:00Z", null)).toBe(false);
    expect(esNueva("2026-09-02T00:00:00Z", undefined)).toBe(false);
  });

  it("se abstiene con fechas ilegibles en cualquiera de los dos lados", () => {
    expect(esNueva("no es una fecha", "2026-09-01T10:00:00Z")).toBe(false);
    expect(esNueva("2026-09-02T00:00:00Z", "tampoco")).toBe(false);
    expect(esNueva(null, "2026-09-01T10:00:00Z")).toBe(false);
  });
});
