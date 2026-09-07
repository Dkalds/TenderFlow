/**
 * Etiquetado de la ficha de webhook.
 *
 * `esFormatoConocido` sustituyó a un `as "json" | "slack_blocks" |
 * "teams_adaptive_card"` sobre el valor que devuelve el `Select`: el cast
 * afirmaba lo que nadie comprobaba, así que un valor fuera de catálogo habría
 * viajado tal cual al cuerpo del alta y el 422 habría llegado del backend. Es
 * la única lógica nueva del troceado de `webhooks-view.tsx` y por eso tiene
 * prueba propia.
 */
import { describe, expect, it } from "vitest";

import {
  FORMATO_LABEL,
  FORMATO_VALUES,
  esFormatoConocido,
  formatDate,
} from "../webhooks/formato";

describe("catálogo de formatos", () => {
  it("cada formato ofrecido tiene su etiqueta en castellano", () => {
    for (const value of FORMATO_VALUES) {
      expect(FORMATO_LABEL[value]).toBeTruthy();
    }
  });

  it("los tres formatos son los que declara el contrato", () => {
    // Si el backend añade uno, este test cae y obliga a decidir su etiqueta en
    // vez de que el selector lo pinte con su nombre técnico.
    expect([...FORMATO_VALUES]).toEqual(["json", "slack_blocks", "teams_adaptive_card"]);
  });
});

describe("esFormatoConocido", () => {
  it.each([...FORMATO_VALUES])("acepta %s", (value) => {
    expect(esFormatoConocido(value)).toBe(true);
  });

  it.each(["", "JSON", "slack", "discord_embed"])("rechaza «%s»", (value) => {
    expect(esFormatoConocido(value)).toBe(false);
  });
});

describe("formatDate", () => {
  it("sin fecha de entrega devuelve el guion, no «Invalid Date»", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
    expect(formatDate("")).toBe("—");
  });

  it("una fecha ilegible tampoco se pinta cruda", () => {
    expect(formatDate("no-es-una-fecha")).toBe("—");
  });

  it("una fecha válida sí se formatea", () => {
    // No se compara con un literal: el formato lo decide `lib/utils` y depende
    // del locale. Lo que importa aquí es que no cae al guion.
    expect(formatDate("2026-09-06T10:30:00Z")).not.toBe("—");
  });
});
