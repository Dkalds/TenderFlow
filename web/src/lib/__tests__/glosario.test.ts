import { describe, it, expect } from "vitest";
import {
  GLOSARIO,
  estadosSinGlosario,
  glosario,
  glosarioDeOpcion,
} from "@/lib/glosario";
import { ESTADO_LABELS } from "@/lib/estados";

describe("glosario", () => {
  it("explica todos los estados que la consola sabe etiquetar", () => {
    // Criterio de aceptación de F1.8. Un estado nuevo en `estados.ts` sin
    // definición falla aquí, que es el único sitio donde el fallo es barato.
    expect(estadosSinGlosario()).toEqual([]);
  });

  it("cubre el vocabulario que el plan enumera", () => {
    for (const clave of ["baja", "ute", "pyme", "valor_estimado", "lote"]) {
      expect(glosario(clave), clave).toBeDefined();
    }
  });

  it("resuelve por código de estado y por concepto, sin importar la caja", () => {
    expect(glosario("ADJ")?.termino).toBe("Adjudicada");
    expect(glosario("adj")?.termino).toBe("Adjudicada");
    expect(glosario("BAJA")?.termino).toBe("Baja");
    expect(glosario("  baja  ")?.termino).toBe("Baja");
  });

  it("devuelve undefined para lo que no sabe explicar", () => {
    expect(glosario("no-existe")).toBeUndefined();
    expect(glosario("")).toBeUndefined();
    expect(glosario(null)).toBeUndefined();
    expect(glosario(undefined)).toBeUndefined();
  });

  it("la etiqueta del glosario coincide con la de estados.ts", () => {
    // Dos textos para el mismo código serían dos productos distintos en la
    // misma pantalla: la tabla diciendo una cosa y su ayuda otra.
    for (const [codigo, etiqueta] of Object.entries(ESTADO_LABELS)) {
      expect(glosario(codigo)?.termino, codigo).toBe(etiqueta);
    }
  });

  it("toda entrada tiene término y definición no vacíos", () => {
    for (const [clave, entrada] of Object.entries(GLOSARIO)) {
      expect(entrada.termino.trim(), clave).not.toBe("");
      expect(entrada.definicion.trim().length, clave).toBeGreaterThan(20);
    }
  });

  it("adapta una opción de lista controlada de la API sin copiarla", () => {
    // F1.7 sirve procedimiento y tramitación desde `GET /meta/filters`; el
    // glosario los pinta con el mismo componente pero no los guarda.
    const entrada = glosarioDeOpcion({
      etiqueta: "Abierto simplificado",
      descripcion: "Abierto con plazos y trámites reducidos.",
    });
    expect(entrada.termino).toBe("Abierto simplificado");
    expect(entrada.definicion).toBe("Abierto con plazos y trámites reducidos.");
    expect(GLOSARIO["Abierto simplificado"]).toBeUndefined();
  });
});
