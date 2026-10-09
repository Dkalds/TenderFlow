/**
 * La disposición de la red de alianzas (`_hooks/utes-red.ts`).
 *
 * Lo que se fija: que la red sólo coloca lo que la API mandó —un nodo por
 * empresa, una arista por par, con sus cifras intactas—, que la colocación no
 * depende del orden en que lleguen los pares, y que elegir una empresa resalta
 * sus alianzas y atenúa el resto sin tocar ninguna cifra.
 */
import { describe, expect, it } from "vitest";

import type { Schemas } from "@/lib/api-types";

import { RED_ALTO, RED_ANCHO, disponerRed, marcarSeleccion } from "../_hooks/utes-red";

type SocioPar = Schemas["UTESocioPar"];

const par = (empresa_a: string, empresa_b: string, contratos: number, importe = contratos * 1_000_000): SocioPar => ({
  empresa_a,
  empresa_b,
  contratos,
  importe,
});

/** ACME es el nodo con más pares; DELTA y EPSILON forman una isla aparte. */
const PARES: SocioPar[] = [
  par("ACME", "BETA", 9),
  par("ACME", "GAMMA", 4),
  par("ACME", "ZETA", 2),
  par("BETA", "GAMMA", 3),
  par("DELTA", "EPSILON", 5),
];

describe("disponerRed", () => {
  it("sin pares no hay nada que colocar", () => {
    expect(disponerRed([])).toEqual({ nodos: [], aristas: [] });
  });

  it("pone un nodo por empresa, aunque salga en varios pares", () => {
    const { nodos } = disponerRed(PARES);
    const nombres = nodos.map((n) => n.nombre);
    expect(nombres).toHaveLength(6);
    expect(new Set(nombres).size).toBe(6);
  });

  it("empieza por la empresa con más pares y sigue por sus socios, del más repetido al menos", () => {
    const { nodos } = disponerRed(PARES);
    // ACME (3 pares) → sus socios por UTE firmadas (BETA 9, GAMMA 4, ZETA 2) →
    // la isla, que no cuelga de nadie, al final y por orden de nombre.
    expect(nodos.map((n) => n.nombre)).toEqual(["ACME", "BETA", "GAMMA", "ZETA", "DELTA", "EPSILON"]);
  });

  it("reparte ese orden de arriba abajo, una a la derecha y la siguiente a la izquierda", () => {
    const { nodos } = disponerRed(PARES);
    const de = (nombre: string) => nodos.find((n) => n.nombre === nombre) as (typeof nodos)[number];
    expect(nodos.map((n) => n.ancla)).toEqual(["start", "end", "start", "end", "start", "end"]);
    // La empresa con más pares, arriba; sus socios, a un lado y a otro por debajo.
    expect(de("ACME").y).toBeLessThan(de("GAMMA").y);
    expect(de("BETA").y).toBeLessThan(de("ZETA").y);
    expect(de("GAMMA").y).toBeLessThan(de("DELTA").y);
    // El par suelto queda enfrentado: sus dos empresas a la misma altura.
    expect(de("DELTA").y).toBe(de("EPSILON").y);
    expect(de("DELTA").x).toBeGreaterThan(de("EPSILON").x);
  });

  it("coloca lo mismo llegue como llegue la lista", () => {
    const delDerecho = disponerRed(PARES);
    const delReves = disponerRed([...PARES].reverse());
    expect(delReves.nodos).toEqual(delDerecho.nodos);
    // Los pares con las empresas cambiadas de lado tampoco mueven nada.
    const volteados = disponerRed(PARES.map((p) => par(p.empresa_b, p.empresa_a, p.contratos, p.importe)));
    expect(volteados.nodos).toEqual(delDerecho.nodos);
  });

  it("reparte los nodos dentro del lienzo, sin dos en el mismo sitio", () => {
    const { nodos } = disponerRed(PARES);
    for (const nodo of nodos) {
      expect(nodo.x).toBeGreaterThan(0);
      expect(nodo.x).toBeLessThan(RED_ANCHO);
      expect(nodo.y).toBeGreaterThan(0);
      expect(nodo.y).toBeLessThan(RED_ALTO);
    }
    expect(new Set(nodos.map((n) => `${n.x},${n.y}`)).size).toBe(nodos.length);
  });

  it("saca cada etiqueta hacia fuera: a la derecha empieza en el nodo, a la izquierda acaba en él", () => {
    const { nodos } = disponerRed(PARES);
    const centro = RED_ANCHO / 2;
    for (const nodo of nodos) {
      if (nodo.x > centro) {
        expect(nodo.ancla).toBe("start");
        expect(nodo.etiquetaX).toBeGreaterThan(nodo.x);
      } else {
        expect(nodo.ancla).toBe("end");
        expect(nodo.etiquetaX).toBeLessThan(nodo.x);
      }
    }
    expect(nodos.some((n) => n.ancla === "start")).toBe(true);
    expect(nodos.some((n) => n.ancla === "end")).toBe(true);
  });

  it("deja cada etiqueta en su propia línea: los nodos de un mismo lado no comparten altura", () => {
    // Veinte pares sueltos son cuarenta empresas: el peor caso que da la API.
    const sueltos = Array.from({ length: 20 }, (_, i) => par(`A${i}`, `B${i}`, 1));
    const { nodos } = disponerRed(sueltos);
    expect(nodos).toHaveLength(40);
    for (const ancla of ["start", "end"] as const) {
      const alturas = nodos
        .filter((n) => n.ancla === ancla)
        .map((n) => n.y)
        .sort((a, b) => a - b);
      for (let i = 1; i < alturas.length; i += 1) {
        expect(alturas[i] - alturas[i - 1]).toBeGreaterThanOrEqual(14);
      }
    }
  });

  it("recorta la etiqueta de un nombre largo y conserva el nombre entero", () => {
    const largo = "INDRA SOLUCIONES TECNOLOGIAS DE LA INFORMACION";
    const { nodos } = disponerRed([par(largo, "BETA", 2)]);
    const nodo = nodos.find((n) => n.nombre === largo);
    expect(nodo?.etiqueta.endsWith("…")).toBe(true);
    expect(nodo?.etiqueta.length).toBeLessThan(largo.length);
    expect(nodos.find((n) => n.nombre === "BETA")?.etiqueta).toBe("BETA");
  });

  it("traza una arista por par, de nodo a nodo y con las cifras de la API", () => {
    const { nodos, aristas } = disponerRed(PARES);
    expect(aristas).toHaveLength(PARES.length);
    const posicion = new Map(nodos.map((n) => [n.nombre, n]));
    aristas.forEach((arista, i) => {
      expect(arista.a).toBe(PARES[i].empresa_a);
      expect(arista.b).toBe(PARES[i].empresa_b);
      expect(arista.contratos).toBe(PARES[i].contratos);
      expect(arista.importe).toBe(PARES[i].importe);
      expect([arista.x1, arista.y1]).toEqual([posicion.get(arista.a)?.x, posicion.get(arista.a)?.y]);
      expect([arista.x2, arista.y2]).toEqual([posicion.get(arista.b)?.x, posicion.get(arista.b)?.y]);
      // A una décima: las coordenadas se redondean para no arrastrar decimales.
      expect(Math.abs(arista.medioX - (arista.x1 + arista.x2) / 2)).toBeLessThanOrEqual(0.1);
      expect(Math.abs(arista.medioY - (arista.y1 + arista.y2) / 2)).toBeLessThanOrEqual(0.1);
    });
    expect(new Set(aristas.map((a) => a.clave)).size).toBe(aristas.length);
  });

  it("engorda la línea con las UTE firmadas, hasta un tope", () => {
    const { aristas } = disponerRed([par("A", "B", 1), par("A", "C", 5), par("A", "D", 400)]);
    const [una, cinco, muchas] = aristas.map((a) => a.grosor);
    expect(una).toBeLessThan(cinco);
    expect(cinco).toBeLessThan(muchas);
    expect(muchas).toBeLessThanOrEqual(12);
    // Un par con una sola UTE se queda fino aunque sea el máximo del ámbito.
    expect(disponerRed([par("A", "B", 1)]).aristas[0].grosor).toBeLessThan(3);
  });
});

describe("marcarSeleccion", () => {
  const red = disponerRed(PARES);
  const estadoDe = (marcada: ReturnType<typeof marcarSeleccion>) =>
    Object.fromEntries(marcada.nodos.map((n) => [n.nombre, n.estado]));

  it("sin empresa elegida todo queda igual", () => {
    const marcada = marcarSeleccion(red, null);
    expect(marcada.elegida).toBeNull();
    expect(marcada.nodos.every((n) => n.estado === "normal")).toBe(true);
    expect(marcada.aristas.every((a) => a.estado === "normal")).toBe(true);
  });

  it("resalta la elegida y sus socios, y atenúa a los demás", () => {
    const marcada = marcarSeleccion(red, "BETA");
    expect(marcada.elegida).toBe("BETA");
    expect(estadoDe(marcada)).toEqual({
      ACME: "socio",
      BETA: "elegido",
      GAMMA: "socio",
      ZETA: "atenuado",
      DELTA: "atenuado",
      EPSILON: "atenuado",
    });
  });

  it("resalta sólo las líneas que tocan a la elegida", () => {
    const marcada = marcarSeleccion(red, "BETA");
    expect(marcada.aristas.map((a) => [a.a, a.b, a.estado])).toEqual([
      ["ACME", "BETA", "resaltada"],
      ["ACME", "GAMMA", "atenuada"],
      ["ACME", "ZETA", "atenuada"],
      ["BETA", "GAMMA", "resaltada"],
      ["DELTA", "EPSILON", "atenuada"],
    ]);
  });

  it("una elegida que ya no está en la red no deja nada marcado", () => {
    // Pasa al cambiar el ámbito: la empresa elegida deja de tener pares.
    const marcada = marcarSeleccion(red, "YA NO ESTÁ");
    expect(marcada.elegida).toBeNull();
    expect(marcada.nodos.every((n) => n.estado === "normal")).toBe(true);
  });
});
