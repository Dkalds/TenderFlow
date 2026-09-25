import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { queryActual, reemplazarQuery } from "@/lib/url-superficial";

/**
 * Lo que fija este suite de `lib/url-superficial.ts`:
 *
 * 1. La query nueva sustituye a la actual sin navegar: el path y el fragmento
 *    no se tocan y el historial no crece.
 * 2. El estado que se escribe es `null`. El parche de Next deja pasar sin
 *    sincronizar `useSearchParams` cualquier estado que ya lleve su marca
 *    `__NA`, así que pasar `history.state` rompería la integración en silencio.
 * 3. Se lee la URL viva, y una escritura que no cambia nada no escribe.
 */

beforeEach(() => {
  window.history.replaceState(null, "", "/mercado?vista=tiempo&ccaa=MD#tabla");
});

afterEach(() => {
  vi.restoreAllMocks();
});

function query(): URLSearchParams {
  return new URLSearchParams(window.location.search);
}

describe("queryActual", () => {
  it("lee la barra de direcciones en cada llamada, no una copia", () => {
    expect(queryActual().get("vista")).toBe("tiempo");
    window.history.replaceState(null, "", "/mercado?vista=cpv");
    expect(queryActual().get("vista")).toBe("cpv");
  });
});

describe("reemplazarQuery", () => {
  it("cambia la query en su sitio: mismo path, mismo fragmento y sin apilar historial", () => {
    const entradas = window.history.length;
    const siguiente = queryActual();
    siguiente.set("vista", "organos");

    reemplazarQuery(siguiente);

    expect(window.location.pathname).toBe("/mercado");
    expect(window.location.hash).toBe("#tabla");
    expect(query().get("vista")).toBe("organos");
    expect(query().get("ccaa")).toBe("MD");
    expect(window.history.length).toBe(entradas);
  });

  it("escribe con estado `null`, que es lo que Next sincroniza con `useSearchParams`", () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    const siguiente = queryActual();
    siguiente.set("vista", "cpv");

    reemplazarQuery(siguiente);

    expect(replaceState).toHaveBeenCalledTimes(1);
    expect(replaceState).toHaveBeenCalledWith(null, "", "/mercado?vista=cpv&ccaa=MD#tabla");
  });

  it("una query vacía no deja un `?` colgando", () => {
    reemplazarQuery(new URLSearchParams());

    expect(window.location.href).toBe(`${window.location.origin}/mercado#tabla`);
  });

  it("si la URL ya dice eso, no escribe nada", () => {
    const replaceState = vi.spyOn(window.history, "replaceState");

    reemplazarQuery(new URLSearchParams("vista=tiempo&ccaa=MD"));

    expect(replaceState).not.toHaveBeenCalled();
  });
});
