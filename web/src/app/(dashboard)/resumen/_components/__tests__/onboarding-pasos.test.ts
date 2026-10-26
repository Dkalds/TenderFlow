import { describe, it, expect } from "vitest";
import {
  debeMostrarse,
  derivarPasos,
  estadoDe,
  etiquetaProgreso,
  progresoDe,
  progresoParaTelemetria,
  PASOS,
} from "@/components/onboarding/pasos";
import { faltaCapacidad, hayNif, hayRegla, tienePursuits } from "@/components/onboarding/senales";
import { senalCapacidad } from "@/components/onboarding/use-estado-onboarding";
import type { Schemas, WatchlistRuleOut } from "@/lib/api-types";
import { findConsoleSpace } from "@/lib/console-spaces";

/**
 * La regla que estos tests protegen es una sola, y es la que hace que la banda
 * sea honesta: **cargando no es «te falta»**. Colapsar los tres estados de una
 * query en un booleano haría que la pantalla de entrada abriese, durante unos
 * cientos de milisegundos, acusando de no tener configurado algo que sí está.
 */

describe("estadoDe", () => {
  it("distingue los cuatro casos sin colapsar cargando en pendiente", () => {
    expect(estadoDe(true)).toBe("hecho");
    expect(estadoDe(false)).toBe("pendiente");
    expect(estadoDe("cargando")).toBe("cargando");
    expect(estadoDe("error")).toBe("desconocido");
    expect(estadoDe(undefined)).toBe("desconocido");
  });
});

describe("debeMostrarse", () => {
  it("con todo hecho, la banda no existe", () => {
    const pasos = derivarPasos({ capacidad: true, alerta: true, pursuit: true });
    expect(debeMostrarse(pasos)).toBe(false);
  });

  it("mientras se comprueba tampoco aparece", () => {
    const pasos = derivarPasos({ capacidad: "cargando", alerta: "cargando", pursuit: "cargando" });
    expect(debeMostrarse(pasos)).toBe(false);
  });

  it("una API rota no inventa una banda de bienvenida", () => {
    const pasos = derivarPasos({ capacidad: "error", alerta: "error", pursuit: "error" });
    expect(debeMostrarse(pasos)).toBe(false);
  });

  it("basta un pendiente acreditado para que valga la pena", () => {
    const pasos = derivarPasos({ capacidad: true, alerta: false, pursuit: "cargando" });
    expect(debeMostrarse(pasos)).toBe(true);
  });
});

describe("progresoDe / etiquetaProgreso", () => {
  it("no cuenta como hecho lo que no ha resuelto", () => {
    const progreso = progresoDe(derivarPasos({ capacidad: true, alerta: false, pursuit: "cargando" }));
    expect(progreso).toEqual({ hechos: 1, total: PASOS.length, sinResolver: 1 });
  });

  it("declara lo que falta por comprobar en vez de dar un total limpio", () => {
    expect(etiquetaProgreso({ hechos: 1, total: 3, sinResolver: 1 })).toBe(
      "1 de 3 hechos · 1 sin comprobar",
    );
    expect(etiquetaProgreso({ hechos: 2, total: 3, sinResolver: 0 })).toBe("2 de 3 hechos");
  });
});

describe("progresoParaTelemetria", () => {
  /**
   * El catálogo de telemetría sólo admite dimensiones enumerables leyendo el
   * fichero (`lib/analytics.ts` §1). Lo que se fija aquí es esa promesa: la
   * dimensión no puede convertirse en un contador libre por la puerta de atrás.
   */
  it("manda el número de pasos hechos como categoría, no como número", () => {
    expect(progresoParaTelemetria({ hechos: 0, total: 3, sinResolver: 0 })).toBe("0");
    expect(progresoParaTelemetria({ hechos: 1, total: 3, sinResolver: 0 })).toBe("1");
    expect(progresoParaTelemetria({ hechos: 2, total: 3, sinResolver: 0 })).toBe("2");
  });

  it("lo que está sin comprobar no cuenta como hecho", () => {
    const progreso = progresoDe(derivarPasos({ capacidad: true, alerta: "error", pursuit: false }));
    expect(progresoParaTelemetria(progreso)).toBe("1");
  });

  it("un cuarto paso no abriría la cardinalidad de la métrica", () => {
    // La banda no se pinta con todo hecho, así que "3" no es alcanzable hoy;
    // el tope existe para que añadir un paso mañana tampoco lo vuelva posible
    // sin que nadie lo decida.
    expect(progresoParaTelemetria({ hechos: 3, total: 4, sinResolver: 0 })).toBe("2");
  });
});

describe("faltaCapacidad", () => {
  const capacidad = (
    campos_incompletos: Schemas["OrganizationCapabilitiesOut"]["campos_incompletos"],
  ): Schemas["OrganizationCapabilitiesOut"] => ({ organization_id: 1, campos_incompletos });

  it("lo decide `campos_incompletos` del backend, no una cuenta del cliente", () => {
    expect(faltaCapacidad(capacidad(["certificaciones", "facturacion", "referencias", "perfiles_equipo"]))).toBe(
      true,
    );
    expect(faltaCapacidad(capacidad(["facturacion"]))).toBe(true);
    expect(faltaCapacidad(capacidad(["certificaciones"]))).toBe(true);
  });

  it("referencias y perfiles de equipo no los exige el paso", () => {
    expect(faltaCapacidad(capacidad(["referencias", "perfiles_equipo"]))).toBe(false);
    expect(faltaCapacidad(capacidad([]))).toBe(false);
  });
});

describe("hayNif", () => {
  it("hace falta al menos uno", () => {
    expect(hayNif({ organization_id: 1, nifs: [] })).toBe(false);
    expect(
      hayNif({ organization_id: 1, nifs: [{ id: 1, nif: "B12345678", razon_social: "Acme", principal: true, created_at: "2026-10-01T00:00:00Z" }] }),
    ).toBe(true);
  });
});

describe("senalCapacidad", () => {
  it("lo que falta del perfil basta para «pendiente», sin esperar al NIF", () => {
    expect(senalCapacidad(false, "cargando")).toBe(false);
    expect(senalCapacidad(false, "error")).toBe(false);
  });

  it("«hecho» exige perfil completo y NIF", () => {
    expect(senalCapacidad(true, true)).toBe(true);
    expect(senalCapacidad(true, false)).toBe(false);
  });

  it("sin poder leer el NIF no se afirma hecho", () => {
    expect(senalCapacidad(true, "error")).toBe("error");
    expect(senalCapacidad(true, "cargando")).toBe("cargando");
  });

  it("mientras el perfil carga o falla, eso es lo que se dice", () => {
    expect(senalCapacidad("cargando", true)).toBe("cargando");
    expect(senalCapacidad("error", true)).toBe("error");
  });
});

describe("hayRegla", () => {
  const regla = (active: boolean): WatchlistRuleOut => ({
    id: 1,
    active,
    email: null,
    frequency: "daily",
    match_count: 0,
    visibility: "private",
  });

  it("sin reglas, paso pendiente", () => {
    expect(hayRegla([])).toBe(false);
  });

  it("el paso es revisarla: una regla pausada también está revisada", () => {
    expect(hayRegla([regla(false)])).toBe(true);
    expect(hayRegla([regla(true)])).toBe(true);
  });
});

describe("tienePursuits", () => {
  it("usa el total del backend, no la longitud de la página devuelta", () => {
    expect(tienePursuits({ total: 0 })).toBe(false);
    expect(tienePursuits({ total: 1 })).toBe(true);
  });
});

describe("PASOS — iconos", () => {
  it("cada paso lleva el icono que su espacio de destino lleva en el rail", () => {
    for (const paso of PASOS) {
      expect(paso.icon, paso.id).toBe(findConsoleSpace(paso.href)?.icon);
    }
  });
});
