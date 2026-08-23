import { describe, expect, it } from "vitest";
import { CCAA_SIN_ASIGNAR, rutaHubCcaa, rutaHubCpv, rutaLicitacion, slugCcaa, slugificar } from "../slug";

describe("slugificar", () => {
  it("pliega los diacríticos en vez de comérselos", () => {
    // El motivo por el que `slugificar` delega en `foldText`: sin NFD, la ó
    // sería un carácter no [a-z0-9] y saldría "contrataci-n".
    expect(slugificar("Contratación Pública")).toBe("contratacion-publica");
  });

  it("colapsa cualquier racha de caracteres no alfanuméricos en un solo guion", () => {
    expect(slugificar("Obras   //  varias --- 2026")).toBe("obras-varias-2026");
  });

  it("no deja guiones sueltos en los extremos", () => {
    expect(slugificar("  ¡Suministro!  ")).toBe("suministro");
  });

  it("devuelve cadena vacía cuando no queda nada que slugificar", () => {
    expect(slugificar("¿¡—!?")).toBe("");
    expect(slugificar("")).toBe("");
  });

  it("recorta a 80 caracteres sin dejar un guion colgando en el corte", () => {
    // El corte cae justo detrás de un guion; el `.replace(/-+$/)` final existe
    // para este caso, que el trim anterior no puede prever.
    const largo = `${"a".repeat(79)} palabra`;
    const slug = slugificar(largo);

    expect(slug.length).toBeLessThanOrEqual(80);
    expect(slug.endsWith("-")).toBe(false);
    expect(slug).toBe("a".repeat(79));
  });
});

describe("slugCcaa", () => {
  it("slugifica una comunidad normal", () => {
    expect(slugCcaa("Castilla y León")).toBe("castilla-y-leon");
  });

  it.each([null, undefined, "", "   ", "—"])(
    "cae en la reserva cuando no hay comunidad utilizable: %s",
    (valor) => {
      expect(slugCcaa(valor)).toBe(CCAA_SIN_ASIGNAR);
    },
  );
});

describe("rutaLicitacion", () => {
  it("deja la referencia suelta en su propio segmento", () => {
    // La referencia base64url puede contener guiones: por eso va en un cuarto
    // segmento y no pegada al slug.
    const ruta = rutaLicitacion({
      ccaa: "Comunidad de Madrid",
      titulo: "Servicio de mantenimiento",
      ref: "ab-c_d",
    });

    expect(ruta).toBe("/licitaciones/comunidad-de-madrid/servicio-de-mantenimiento/ab-c_d");
    expect(ruta.split("/")).toHaveLength(5);
  });

  it("usa una reserva de slug para que un título impronunciable no rompa la ruta", () => {
    // Sin la reserva saldría "/licitaciones/sin-comunidad//ref", que Next
    // normaliza a otra cosa y deja la página inalcanzable.
    expect(rutaLicitacion({ ccaa: null, titulo: "¿?", ref: "R1" })).toBe(
      `/licitaciones/${CCAA_SIN_ASIGNAR}/licitacion/R1`,
    );
  });
});

describe("rutaHubCcaa", () => {
  it("apunta al hub de la comunidad", () => {
    expect(rutaHubCcaa("Galicia")).toBe("/licitaciones/galicia");
  });

  it("manda los expedientes sin comunidad al hub de reserva", () => {
    expect(rutaHubCcaa(undefined)).toBe(`/licitaciones/${CCAA_SIN_ASIGNAR}`);
  });
});

describe("rutaHubCpv", () => {
  it("se queda solo con los dígitos", () => {
    expect(rutaHubCpv("72-00.00.00")).toBe("/cpv/72000000");
  });

  it("trunca a ocho dígitos", () => {
    expect(rutaHubCpv("7200000012345")).toBe("/cpv/72000000");
  });

  it("tolera un código sin dígitos", () => {
    expect(rutaHubCpv("sin-codigo")).toBe("/cpv/");
  });
});
