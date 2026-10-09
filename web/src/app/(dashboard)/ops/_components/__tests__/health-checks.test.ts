import { describe, expect, it } from "vitest";
import {
  componentesDeSalud,
  estadoComponente,
  estadoGlobal,
  type HealthResponse,
} from "../observabilidad/health-checks";

/**
 * La lectura de `/api/v1/health`, contra la forma que la API devuelve de verdad.
 *
 * El semáforo daba por sana cualquier respuesta sin error de red: un `degraded`
 * llega con HTTP 200, así que con Redis caído o el esquema atrasado la cabecera
 * seguía diciendo «En línea · Todos los servicios responden». Y el esquema, que
 * viaja como cadena en `schema_revision`, ni siquiera entraba en la rejilla.
 */

const SANO: HealthResponse = {
  status: "ok",
  db: "ok",
  redis: "ok",
  disk: "ok",
  schema_revision: "ok (v146_lic_organo_norm_index)",
  timestamp: "2026-10-09T01:42:30+00:00",
};

const QUIETO = { cargando: false, fallo: false };

describe("estadoGlobal", () => {
  it("es ok cuando la API dice ok", () => {
    expect(estadoGlobal(SANO, QUIETO)).toBe("ok");
  });

  it("un degraded con HTTP 200 no es «en línea»", () => {
    const health = { ...SANO, status: "degraded", redis: "degraded" };
    expect(estadoGlobal(health, QUIETO)).toBe("degradado");
  });

  it("sin respuesta o con la llamada caída es error", () => {
    expect(estadoGlobal(undefined, { cargando: false, fallo: true })).toBe("error");
    expect(estadoGlobal(undefined, QUIETO)).toBe("error");
  });

  it("mientras carga no afirma nada", () => {
    expect(estadoGlobal(undefined, { cargando: true, fallo: false })).toBe("comprobando");
  });

  it("sin `status`, lo deduce de los componentes", () => {
    const { status: _status, ...sinStatus } = SANO;
    expect(estadoGlobal(sinStatus, QUIETO)).toBe("ok");
    expect(estadoGlobal({ ...sinStatus, db: "error" }, QUIETO)).toBe("degradado");
  });
});

describe("estadoComponente", () => {
  it.each([
    ["ok", "ok"],
    ["ok (v146_lic_organo_norm_index)", "ok"],
    ["connected", "ok"],
    ["degraded", "aviso"],
    ["low (120 MB free, min 500 MB)", "aviso"],
    ["behind (v140 < v146)", "aviso"],
    ["ahead (v147)", "aviso"],
    ["error", "error"],
  ] as const)("%s → %s", (valor, esperado) => {
    expect(estadoComponente(valor)).toBe(esperado);
  });

  it.each(["unconfigured", "unknown", "", undefined, null])(
    "%s no es un fallo: es que no se mide",
    (valor) => {
      // Redis sin configurar salía con insignia roja de «Error».
      expect(estadoComponente(valor)).toBe("sin_dato");
    },
  );
});

describe("componentesDeSalud", () => {
  it("incluye el esquema, que viaja como cadena en `schema_revision`", () => {
    const componentes = componentesDeSalud({ ...SANO, schema_revision: "behind (v140 < v146)" });

    expect(componentes.map((c) => c.clave)).toEqual(["db", "redis", "disk", "schema_revision"]);
    const esquema = componentes.find((c) => c.clave === "schema_revision");
    expect(esquema).toMatchObject({
      nombre: "Esquema de la base de datos",
      estado: "aviso",
      detalle: "behind (v140 < v146)",
    });
  });

  it("no inventa componentes que la respuesta no trae", () => {
    expect(componentesDeSalud({ status: "ok", db: "ok" }).map((c) => c.clave)).toEqual(["db"]);
    expect(componentesDeSalud(undefined)).toEqual([]);
  });

  it("no cuenta como componente lo que describe al servicio", () => {
    const claves = componentesDeSalud(SANO).map((c) => c.clave);
    expect(claves).not.toContain("status");
    expect(claves).not.toContain("timestamp");
  });
});
