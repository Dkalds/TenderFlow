/**
 * Todo evento del catálogo `EventosProducto` tiene al menos un emisor.
 *
 * Un evento declarado y nunca emitido es peor que no tenerlo: el panel de
 * Vercel enseña una serie a cero y quien la mira concluye «nadie usa esto»
 * cuando la verdad es «nadie lo mide». La auditoría del 2026-10-23 los repasó
 * uno a uno —los 23 tienen emisor— y este test es lo que impide que el
 * siguiente evento entre en el catálogo sin su `registrarEvento`.
 *
 * Es un escaneo de texto sobre `web/src` (sin tests ni código generado): busca
 * `registrarEvento("<evento>"`, con la llamada partida en varias líneas o no.
 * El nombre es un literal en todas las llamadas porque el tipo lo exige
 * (`E extends EventoProducto`), así que el escaneo no tiene falsos negativos
 * por nombres construidos.
 */
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { PROPIEDADES_PERMITIDAS, type EventoProducto } from "@/lib/analytics";

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

/**
 * Eventos del catálogo que pueden quedarse sin emisor, cada uno con su motivo.
 *
 * Vacía a propósito: hoy no hay ninguno. Una entrada aquí es deuda declarada
 * (p. ej. «el emisor cae en una pantalla que otra rama está rehaciendo;
 * pendiente tras integración»), y el segundo test obliga a borrarla en cuanto
 * el emisor aparece.
 */
const SIN_EMISOR_JUSTIFICADO: Partial<Record<EventoProducto, string>> = {};

function ficherosFuente(dir: string): string[] {
  const salida: string[] = [];
  for (const entrada of readdirSync(dir, { withFileTypes: true })) {
    const ruta = path.join(dir, entrada.name);
    if (entrada.isDirectory()) {
      if (entrada.name === "__tests__" || entrada.name === "generated") continue;
      salida.push(...ficherosFuente(ruta));
    } else if (/\.tsx?$/.test(entrada.name) && !/\.(test|spec)\.tsx?$/.test(entrada.name)) {
      salida.push(ruta);
    }
  }
  return salida;
}

function eventosEmitidos(): Set<string> {
  const emitidos = new Set<string>();
  const patron = /registrarEvento\(\s*"(\w+)"/g;
  for (const fichero of ficherosFuente(SRC)) {
    for (const coincidencia of readFileSync(fichero, "utf8").matchAll(patron)) {
      emitidos.add(coincidencia[1]);
    }
  }
  return emitidos;
}

describe("catálogo de eventos de producto", () => {
  const catalogo = Object.keys(PROPIEDADES_PERMITIDAS) as EventoProducto[];
  const emitidos = eventosEmitidos();

  it("el escaneo encuentra emisores (si no, el test no estaría mirando nada)", () => {
    expect(catalogo.length).toBeGreaterThan(0);
    expect(emitidos.size).toBeGreaterThan(0);
  });

  it("todo evento del catálogo tiene al menos un registrarEvento", () => {
    const sinEmisor = catalogo.filter(
      (evento) => !emitidos.has(evento) && !(evento in SIN_EMISOR_JUSTIFICADO),
    );
    expect(sinEmisor).toEqual([]);
  });

  it("una excepción no sobrevive a su emisor", () => {
    const obsoletas = Object.keys(SIN_EMISOR_JUSTIFICADO).filter((evento) =>
      emitidos.has(evento),
    );
    expect(obsoletas).toEqual([]);
  });

  it("no se emite ningún evento fuera del catálogo", () => {
    const fuera = [...emitidos].filter((evento) => !(evento in PROPIEDADES_PERMITIDAS));
    expect(fuera).toEqual([]);
  });
});
