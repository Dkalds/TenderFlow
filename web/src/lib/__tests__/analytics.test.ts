/**
 * Tests de `web/src/lib/analytics.ts`.
 *
 * Lo que se fija aquí no es "que se llame a track": es que las tres promesas
 * del módulo se cumplan aunque alguien las esquive. Los nombres y las
 * propiedades están tipados (los `@ts-expect-error` fallan el `tsc --noEmit` si
 * el tipo deja de proteger), una propiedad fuera de la allowlist no sale del
 * proceso aunque el tipo se haya burlado con un `as`, y un `track` que revienta
 * no puede propagar hacia la mutación que lo llamó.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("@vercel/analytics", () => ({ track: vi.fn() }));

import { track } from "@vercel/analytics";
import {
  dimensionesDeDescarga,
  primeraVez,
  registrarEvento,
  PROPIEDADES_PERMITIDAS,
  type EventoProducto,
} from "@/lib/analytics";

const trackMock = vi.mocked(track);

beforeEach(() => {
  trackMock.mockReset();
  trackMock.mockImplementation(() => undefined);
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("registrarEvento", () => {
  it("manda el nombre del evento y sus propiedades permitidas", () => {
    registrarEvento("radar_triaje", { accion: "descartar" });

    expect(trackMock).toHaveBeenCalledTimes(1);
    expect(trackMock).toHaveBeenCalledWith("radar_triaje", { accion: "descartar" });
  });

  it("no propaga si `track` revienta: un bloqueador no tumba la mutación", () => {
    trackMock.mockImplementation(() => {
      throw new Error("blocked by client");
    });

    expect(() => registrarEvento("licitacion_seguida", { accion: "seguir" })).not.toThrow();
  });

  it("descarta propiedades fuera de la allowlist aunque el tipo se haya esquivado", () => {
    // Así es exactamente como se cuela una fuga: un objeto construido en otro
    // sitio, casteado al entrar. El filtro en runtime existe para este caso.
    const contaminado = {
      accion: "descartar",
      id_externo: "PA-S 2026/000058",
      email: "cliente@empresa.es",
    } as unknown as { accion: "descartar" };

    registrarEvento("radar_triaje", contaminado);

    expect(trackMock).toHaveBeenCalledWith("radar_triaje", { accion: "descartar" });
  });

  it("descarta valores que no sean strings cortos", () => {
    const contaminado = {
      espacio: "radar",
      origen: "x".repeat(200),
    } as unknown as { espacio: string; origen: "rail" };

    registrarEvento("espacio_abierto", contaminado);

    expect(trackMock).toHaveBeenCalledWith("espacio_abierto", { espacio: "radar" });
  });

  it("rechaza en compilación un evento que no existe", () => {
    // @ts-expect-error nombre de evento inventado: un typo no puede compilar.
    registrarEvento("radar_triage", { accion: "descartar" });
  });

  it("rechaza en compilación un valor fuera de la unión", () => {
    // @ts-expect-error "borrar" no es una acción del triaje del Radar.
    registrarEvento("radar_triaje", { accion: "borrar" });
  });

  it("declara la allowlist de todos los eventos del catálogo", () => {
    // El `satisfies` del módulo ya lo garantiza en compilación; esto lo deja
    // visible en el fallo del test si alguien lo relaja.
    const eventos = Object.keys(PROPIEDADES_PERMITIDAS) as EventoProducto[];
    expect(eventos.length).toBeGreaterThan(0);
    for (const evento of eventos) {
      expect(PROPIEDADES_PERMITIDAS[evento].length).toBeGreaterThan(0);
    }
  });

  it("mantiene el catálogo pequeño: menos eventos bien elegidos que muchos", () => {
    // Guardarraíl explícito del acuerdo de producto, no una constante mágica:
    // pasar de aquí obliga a la conversación de qué se retira, y por eso el
    // tope se sube pegado al tamaño real en vez de dejar hueco libre.
    //
    // Subido de 10 a 11 al cerrar el embudo de activación: `perfil_configurado`
    // y `onboarding_ocultado` son su boca y su fuga, y sin las dos los tres
    // eventos que ya había medían un embudo del que no se veía ni la entrada ni
    // el abandono.
    //
    // Subido de 11 a 13 el 2026-08-30 con `busqueda_realizada` y
    // `vista_guardada`. El embudo seguía empezando en «perfil configurado»,
    // que es ya el segundo o tercer paso de una sesión: no se podía distinguir
    // «entró y no encontró nada» de «entró y no llegó a buscar», y esos dos
    // diagnósticos piden arreglos opuestos —cobertura del corpus frente a
    // descubribilidad de la búsqueda—. `vista_guardada` es el complemento de
    // `regla_creada`: una dice «vuelvo a esto», la otra «avísame de esto».
    expect(Object.keys(PROPIEDADES_PERMITIDAS).length).toBeLessThanOrEqual(13);
  });
});

describe("dimensionesDeDescarga", () => {
  it("saca formato y recurso de la URL de exportación", () => {
    expect(dimensionesDeDescarga("/api/v1/exports/download?format=csv")).toEqual({
      formato: "csv",
      recurso: "exports/download",
    });
  });

  it("no deja pasar la query: ahí van los filtros escritos por el usuario", () => {
    const { recurso } = dimensionesDeDescarga(
      "/api/v1/exports/download?format=xlsx&q=SAP%20Ayuntamiento&organo=Madrid",
    );

    expect(recurso).toBe("exports/download");
    expect(recurso).not.toContain("SAP");
  });

  it("descarta los segmentos que parecen identificadores", () => {
    expect(dimensionesDeDescarga("/api/v1/licitaciones/PA-S%202026%2F000058/export?format=csv")).toEqual({
      formato: "csv",
      recurso: "licitaciones/export",
    });
  });

  it("marca como `otro` un formato desconocido o ausente", () => {
    expect(dimensionesDeDescarga("/api/v1/exports/download").formato).toBe("otro");
    expect(dimensionesDeDescarga("/api/v1/exports/download?format=pdf").formato).toBe("otro");
  });

  it("nunca devuelve un recurso vacío", () => {
    expect(dimensionesDeDescarga("/12345?format=csv").recurso).toBe("otro");
  });
});

describe("primeraVez", () => {
  it("dice `si` una sola vez por navegador", () => {
    expect(primeraVez("pursuit")).toBe("si");
    expect(primeraVez("pursuit")).toBe("no");
  });

  it("cuenta cada marca por separado", () => {
    expect(primeraVez("pursuit")).toBe("si");
    expect(primeraVez("regla")).toBe("si");
  });

  it("responde `desconocido` si no puede sellar: inflar la activación es peor", () => {
    // Estado de partida explícito: sin él, el caso pasaría por el camino de
    // "ya sellado" si otro test dejara la marca puesta, y verde por el motivo
    // equivocado.
    expect(window.localStorage.getItem("lsap:v1:telemetria:primera:pursuit")).toBeNull();

    // El sello lo escribe `setJSON` (lib/storage.ts) a través de
    // `window.localStorage`, y ese objeto no siempre es el mismo: en jsdom es un
    // Proxy cuyos métodos viven en `Storage.prototype` —y cuyo trap
    // `defineProperty` guarda "setItem" como un *item* más en vez de sustituir
    // el método—, mientras que el shim de `src/test/setup.ts` sí es un objeto
    // corriente. Un `vi.spyOn(window.localStorage, "setItem")` sólo se instala
    // en el segundo caso: en el primero `setJSON` seguía escribiendo bien y
    // `primeraVez` respondía "si". Se sustituye el objeto entero, que es el
    // único punto por el que la escritura pasa con seguridad.
    const original = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: almacenamientoSinCupo(),
    });

    try {
      expect(primeraVez("pursuit")).toBe("desconocido");
    } finally {
      if (original) Object.defineProperty(window, "localStorage", original);
      else Reflect.deleteProperty(window, "localStorage");
    }
  });
});

/** Storage que acepta lecturas y revienta al escribir, como el modo privado. */
function almacenamientoSinCupo(): Storage {
  return {
    length: 0,
    clear: () => {},
    getItem: () => null,
    key: () => null,
    removeItem: () => {},
    setItem: () => {
      throw new Error("QuotaExceededError");
    },
  };
}
