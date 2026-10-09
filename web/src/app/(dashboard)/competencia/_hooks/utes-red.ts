/**
 * La disposición de la red de alianzas, como funciones puras.
 *
 * La API manda pares de empresas que han firmado una UTE juntas; aquí sólo se
 * decide dónde va cada una. No hay cifras nuevas: un nodo por empresa, una
 * arista por par con sus UTE y su importe tal cual llegan, y los nodos todos
 * del mismo tamaño porque el contrato no trae cifras por empresa.
 *
 * Los nodos van sobre una elipse, la mitad a cada lado y repartidos a alturas
 * regulares: así cada etiqueta sale hacia fuera en su propia línea y no pisa a
 * la de al lado ni con las cuarenta empresas que caben en veinte pares.
 *
 * El orden recorre la red en anchura desde la empresa con más pares y se
 * reparte de arriba abajo, una a la derecha y la siguiente a la izquierda. La
 * empresa con más alianzas queda arriba con sus socios alrededor, a un lado y a
 * otro, y sus líneas se abren en abanico en vez de amontonarse en un solo
 * arco; un par suelto acaba con sus dos empresas enfrentadas. Todos los
 * desempates son por nombre: la misma lista coloca siempre lo mismo.
 */

import type { Schemas } from "@/lib/api-types";
import { truncate } from "@/lib/utils";

type SocioPar = Schemas["UTESocioPar"];

/** El lienzo de la red, en unidades del `viewBox`. */
export const RED_ANCHO = 760;
export const RED_ALTO = 420;

const CENTRO_X = RED_ANCHO / 2;
const CENTRO_Y = RED_ALTO / 2;
/** Radios de la elipse: el horizontal deja a cada lado el sitio de una etiqueta. */
const RADIO_X = 188;
const RADIO_Y = 176;
/** Del centro del nodo al arranque de su etiqueta. */
const SEPARACION_ETIQUETA = 14;
/** Caracteres de una etiqueta antes de recortarla; el nombre entero va aparte. */
const LARGO_ETIQUETA = 20;

/** Grosor de una línea: lo que mide con cero UTE, lo que suma cada una y el tope. */
const GROSOR_BASE = 1.5;
const GROSOR_POR_UTE = 0.9;
const GROSOR_TOPE = 12;

export interface NodoRed {
  /** El nombre que manda la API: identifica a la empresa en toda la vista. */
  nombre: string;
  /** El nombre recortado para dibujarlo junto al nodo. */
  etiqueta: string;
  x: number;
  y: number;
  /** Dónde arranca (o acaba) la etiqueta, a la altura del nodo. */
  etiquetaX: number;
  /** `start` a la derecha de la elipse, `end` a la izquierda. */
  ancla: "start" | "end";
}

export interface AristaRed {
  clave: string;
  a: string;
  b: string;
  contratos: number;
  importe: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  grosor: number;
  /** El punto medio, donde va la pastilla con el número de UTE. */
  medioX: number;
  medioY: number;
}

export interface Red {
  nodos: NodoRed[];
  aristas: AristaRed[];
}

const redondear = (valor: number) => Math.round(valor * 10) / 10;

const porNombre = (a: string, b: string) => a.localeCompare(b, "es");

/** El recorrido en anchura que decide en qué orden se reparten los nodos. */
function ordenarEmpresas(pares: readonly SocioPar[]): string[] {
  const socios = new Map<string, Map<string, number>>();
  const anotar = (empresa: string, socio: string, contratos: number) => {
    const suyos = socios.get(empresa) ?? new Map<string, number>();
    // Un par repetido no suma: cuenta el que más UTE trae, sólo para ordenar.
    suyos.set(socio, Math.max(suyos.get(socio) ?? 0, contratos));
    socios.set(empresa, suyos);
  };
  for (const par of pares) {
    anotar(par.empresa_a, par.empresa_b, par.contratos);
    anotar(par.empresa_b, par.empresa_a, par.contratos);
  }

  const paresDe = (empresa: string) => socios.get(empresa)?.size ?? 0;
  const arranques = [...socios.keys()].sort((a, b) => paresDe(b) - paresDe(a) || porNombre(a, b));

  const orden: string[] = [];
  const vistas = new Set<string>();
  for (const arranque of arranques) {
    if (vistas.has(arranque)) continue;
    vistas.add(arranque);
    const cola = [arranque];
    while (cola.length > 0) {
      const empresa = cola.shift() as string;
      orden.push(empresa);
      const siguientes = [...(socios.get(empresa) ?? [])]
        .filter(([socio]) => !vistas.has(socio))
        .sort((a, b) => b[1] - a[1] || porNombre(a[0], b[0]));
      for (const [socio] of siguientes) {
        vistas.add(socio);
        cola.push(socio);
      }
    }
  }
  return orden;
}

/**
 * Coloca las empresas de `pares` sobre la elipse y traza sus alianzas.
 *
 * Los nodos salen en el orden del recorrido: los de puesto par bajan por la
 * derecha y los de puesto impar, por la izquierda.
 */
export function disponerRed(pares: readonly SocioPar[]): Red {
  const orden = ordenarEmpresas(pares);
  const aLaDerecha = Math.ceil(orden.length / 2);
  const aLaIzquierda = orden.length - aLaDerecha;

  const nodos = orden.map((nombre, i): NodoRed => {
    const derecha = i % 2 === 0;
    const enSuLado = derecha ? aLaDerecha : aLaIzquierda;
    const fila = Math.floor(i / 2);
    // De -1 (arriba) a 1 (abajo), con cada fila en el centro de su franja.
    const altura = -1 + (2 * fila + 1) / enSuLado;
    const lado = derecha ? 1 : -1;
    const x = redondear(CENTRO_X + lado * RADIO_X * Math.sqrt(1 - altura * altura));
    return {
      nombre,
      etiqueta: truncate(nombre, LARGO_ETIQUETA),
      x,
      y: redondear(CENTRO_Y + RADIO_Y * altura),
      etiquetaX: redondear(x + lado * SEPARACION_ETIQUETA),
      ancla: derecha ? "start" : "end",
    };
  });

  const posicion = new Map(nodos.map((nodo) => [nodo.nombre, nodo]));
  // El paso por UTE se encoge cuando el par más repetido pasaría del tope: así
  // un ámbito con pares de cuarenta UTE no los pinta todos igual de gruesos, y
  // uno con pares de una sola los deja finos.
  const masRepetido = Math.max(1, ...pares.map((par) => par.contratos));
  const porUte = Math.min(GROSOR_POR_UTE, (GROSOR_TOPE - GROSOR_BASE) / masRepetido);

  const aristas = pares.flatMap((par, i): AristaRed[] => {
    const desde = posicion.get(par.empresa_a);
    const hasta = posicion.get(par.empresa_b);
    if (!desde || !hasta) return [];
    return [
      {
        clave: `${i}:${par.empresa_a}:${par.empresa_b}`,
        a: par.empresa_a,
        b: par.empresa_b,
        contratos: par.contratos,
        importe: par.importe,
        x1: desde.x,
        y1: desde.y,
        x2: hasta.x,
        y2: hasta.y,
        grosor: redondear(GROSOR_BASE + par.contratos * porUte),
        medioX: redondear((desde.x + hasta.x) / 2),
        medioY: redondear((desde.y + hasta.y) / 2),
      },
    ];
  });

  return { nodos, aristas };
}

export type EstadoNodo = "normal" | "elegido" | "socio" | "atenuado";
export type EstadoArista = "normal" | "resaltada" | "atenuada";

export interface RedMarcada {
  /** La empresa elegida, o `null` si no hay ninguna o ya no está en la red. */
  elegida: string | null;
  nodos: (NodoRed & { estado: EstadoNodo })[];
  aristas: (AristaRed & { estado: EstadoArista })[];
}

/**
 * Marca la red para una empresa elegida: ella, sus socios y sus líneas quedan a
 * la vista y el resto se atenúa. Sin elegida —o con una que el ámbito actual ya
 * no trae— todo queda como estaba.
 */
export function marcarSeleccion(red: Red, elegida: string | null): RedMarcada {
  const vigente = elegida != null && red.nodos.some((nodo) => nodo.nombre === elegida) ? elegida : null;
  if (vigente == null) {
    return {
      elegida: null,
      nodos: red.nodos.map((nodo) => ({ ...nodo, estado: "normal" })),
      aristas: red.aristas.map((arista) => ({ ...arista, estado: "normal" })),
    };
  }

  const socios = new Set<string>();
  const aristas = red.aristas.map((arista) => {
    const toca = arista.a === vigente || arista.b === vigente;
    if (toca) socios.add(arista.a === vigente ? arista.b : arista.a);
    return { ...arista, estado: toca ? ("resaltada" as const) : ("atenuada" as const) };
  });
  const nodos = red.nodos.map((nodo) => ({
    ...nodo,
    estado:
      nodo.nombre === vigente ? ("elegido" as const) : socios.has(nodo.nombre) ? ("socio" as const) : ("atenuado" as const),
  }));
  return { elegida: vigente, nodos, aristas };
}
