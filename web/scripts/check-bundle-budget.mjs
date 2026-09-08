#!/usr/bin/env node
/**
 * check-bundle-budget.mjs — el peso de cada ruta es un número que solo baja (C7.6).
 *
 * Por qué existe: hasta 2026-09 nada medía el bundle. Una dependencia nueva
 * importada en el sitio equivocado —un `import { algo } from "libreria"` que
 * arrastra la librería entera al First Load de una ruta pública— pasaba la
 * revisión sin que nadie viera el coste, y se descubría meses después mirando
 * el RUM. El analizador (`ANALYZE=1 next build`) enseña QUÉ pesa; esto decide
 * si es demasiado, que es una pregunta distinta y la que puede bloquear.
 *
 * Cómo mide
 * ---------
 * No mide: **lee la medición de Next**. `.next/diagnostics/route-bundle-stats.json`
 * trae, por ruta, el `firstLoadUncompressedJsBytes` que el propio build calcula
 * y que es la columna «First Load JS» de su salida. Recontarlo por nuestra
 * cuenta —sumando los chunks del manifiesto— daría un número parecido y
 * distinto, y entonces el umbral hablaría de una magnitud que no es la que ve
 * cualquiera al compilar.
 *
 * Se lee el artefacto y no el texto de la tabla a propósito: un cambio de
 * formato de la salida rompería un parser, y aquí no rompe nada.
 *
 * Bytes sin comprimir, no gzip. El número absoluto importa menos que su
 * evolución, y el gzip depende de la versión de la librería que lo aplique —lo
 * que haría que el umbral se moviera sin que el bundle cambiara.
 *
 * Los umbrales viven en `bundle-budget.json`, versionados, **medidos** y con la
 * fecha de la medición. Un umbral inventado deja CI en rojo el primer día o no
 * detecta nada nunca; los dos desenlaces acaban con alguien borrando el gate.
 *
 * Uso:
 *     node scripts/check-bundle-budget.mjs            # comprueba
 *     node scripts/check-bundle-budget.mjs --write    # siembra/actualiza el fichero
 *     node scripts/check-bundle-budget.mjs --report   # imprime la tabla y sale 0
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ESTADISTICAS = path.join(RAIZ, ".next", "diagnostics", "route-bundle-stats.json");
const PRESUPUESTO = path.join(RAIZ, "bundle-budget.json");

/**
 * Margen sobre el valor medido, en tanto por uno.
 *
 * Un 5 % absorbe el ruido entre builds (hashes de chunk, orden de módulos) sin
 * dejar pasar una regresión de verdad: lo que este gate persigue es la
 * dependencia nueva que suma decenas de KB, no una variación de tres.
 */
const MARGEN = 0.05;

/** `{ruta: bytes}` — el First Load JS que declara el build. */
function medir() {
  if (!existsSync(ESTADISTICAS)) {
    console.error(
      `No encuentro ${path.relative(RAIZ, ESTADISTICAS)}.\n` +
        "Hay que compilar antes: `npx next build`.",
    );
    process.exit(2);
  }
  const filas = JSON.parse(readFileSync(ESTADISTICAS, "utf8"));
  const medido = {};
  for (const fila of filas) {
    const bytes = fila.firstLoadUncompressedJsBytes;
    // Una ruta sin JS de cliente (un `route.ts`, un sitemap) no tiene First
    // Load que vigilar. Se omite en vez de anotarse con cero: un cero en el
    // presupuesto se leería como «esta ruta no puede crecer nunca».
    if (typeof bytes !== "number" || bytes <= 0) continue;
    medido[fila.route] = bytes;
  }
  return medido;
}

function kb(bytes) {
  return `${(bytes / 1024).toFixed(1)} kB`;
}

function escribir(medido) {
  const rutas = {};
  for (const ruta of Object.keys(medido).sort()) {
    rutas[ruta] = {
      medido: medido[ruta],
      // El umbral se DERIVA del valor medido y del margen: nadie escribe un
      // número a mano, que es como se acaba con un gate que no puede estar
      // verde (ver la calibración de `audit_domain_truth`, C4.5).
      limite: Math.ceil(medido[ruta] * (1 + MARGEN)),
    };
  }
  const contenido = {
    _: "Generado por scripts/check-bundle-budget.mjs --write. Los límites SOLO bajan.",
    margen: MARGEN,
    medido_el: new Date().toISOString().slice(0, 10),
    rutas,
  };
  writeFileSync(PRESUPUESTO, `${JSON.stringify(contenido, null, 2)}\n`, "utf8");
  console.log(
    `Presupuesto escrito en ${path.relative(RAIZ, PRESUPUESTO)} ` +
      `(${Object.keys(rutas).length} rutas, margen ${(MARGEN * 100).toFixed(0)} %).`,
  );
}

function comprobar(medido) {
  if (!existsSync(PRESUPUESTO)) {
    console.error(
      `No hay ${path.relative(RAIZ, PRESUPUESTO)}. Siémbralo con ` +
        "`node scripts/check-bundle-budget.mjs --write` sobre un build limpio.",
    );
    process.exit(2);
  }
  const presupuesto = JSON.parse(readFileSync(PRESUPUESTO, "utf8"));
  const rutas = presupuesto.rutas ?? {};
  const excesos = [];
  const nuevas = [];

  for (const [ruta, bytes] of Object.entries(medido).sort()) {
    const entrada = rutas[ruta];
    if (!entrada) {
      nuevas.push([ruta, bytes]);
      continue;
    }
    if (bytes > entrada.limite) excesos.push([ruta, bytes, entrada.limite]);
  }

  for (const [ruta, bytes, limite] of excesos) {
    console.error(
      `[excede] ${ruta}: ${kb(bytes)} > ${kb(limite)} (+${kb(bytes - limite)} sobre el límite)`,
    );
  }
  for (const [ruta, bytes] of nuevas) {
    // Una ruta nueva no falla —no hay contra qué compararla— pero se anuncia:
    // el `--write` que la incorpore es una decisión, no un descuido.
    console.log(`[nueva] ${ruta}: ${kb(bytes)} — sin límite todavía`);
  }

  if (excesos.length > 0) {
    console.error(
      `\n${excesos.length} ruta(s) por encima de su presupuesto.\n` +
        "El límite solo baja: si el peso subió a propósito, el cambio tiene que " +
        "explicar por qué y actualizar `bundle-budget.json` en el mismo commit.\n" +
        "Para ver qué entró: `ANALYZE=1 npx next build` y abrir el informe.",
    );
    process.exit(1);
  }
  console.log(
    `Presupuesto de bundle OK: ${Object.keys(medido).length} rutas dentro de su límite` +
      `${nuevas.length ? `, ${nuevas.length} sin límite todavía` : ""}.`,
  );
}

function informe(medido) {
  const filas = Object.entries(medido).sort((a, b) => b[1] - a[1]);
  console.log("First Load JS por ruta (mayor primero):");
  for (const [ruta, bytes] of filas) {
    console.log(`  ${kb(bytes).padStart(10)}  ${ruta}`);
  }
}

const medido = medir();
if (process.argv.includes("--write")) escribir(medido);
else if (process.argv.includes("--report")) informe(medido);
else comprobar(medido);
