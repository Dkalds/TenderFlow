/**
 * run-vitest.mjs
 *
 * Envoltorio de `vitest run` que distingue "todo pasó" de "no se ejecutó nada".
 *
 * Por qué existe: vitest devuelve **exit 0** cuando no consigue arrancar sus
 * workers. La salida dice `Test Files  no tests` / `Tests  no tests` junto a N
 * líneas `[vitest-pool]: Failed to start forks worker`, y el proceso termina en
 * 0. Reproducido tres veces (2026-08-18/19) en una máquina Windows con disco
 * lento: con `--pool=forks --no-file-parallelism` corrieron 70 de 113 ficheros
 * con 43 errores y exit 0; con `--pool=forks`, 0 de 113 ficheros, 113 errores y
 * exit 0. Aquí lo dispara la contención de disco, pero la causa de fondo —el
 * runner no distingue un verde de un no-ejecutado— viaja igual a CI: un runner
 * lento allí deja el job `frontend` en verde sin haber probado nada. Es un gate
 * que miente en la dirección peligrosa, porque toda la garantía del frontend
 * cuelga de él.
 *
 * Qué comprueba, además del exit code de vitest:
 *   1. Que el reporter JSON exista y sea parseable (si no hay informe, no hubo
 *      ejecución observable).
 *   2. Que el número de ficheros de test ejecutados supere el ratchet de abajo.
 *   3. Que no haya errores de arranque de pool en la salida, aunque vitest
 *      devuelva 0 y el recuento cuadre (una suite parcial también miente).
 *
 * Uso: `node scripts/run-vitest.mjs [args de vitest...]`.
 * Los argumentos se pasan tal cual (`--coverage`, `--pool=threads`, filtros...).
 * Sin dependencias nuevas: solo Node >= 22.
 */

import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const WEB_DIR = resolve(__dirname, "..");

/**
 * Ratchet: mínimo de ficheros de test que una ejecución completa debe correr.
 *
 * Mismo patrón que `KNOWN_5XX` o la whitelist TID251 del backend: **un número
 * que solo puede subir**. Perder la mitad de la suite no puede pasar por verde,
 * así que el umbral vive aquí, visible, y no en una variable de entorno de CI.
 *
 * Medido 2026-08-27: 127 ficheros bajo web/src que casan con el patrón
 * `include` de vitest.config.ts. Se fija con un margen pequeño por debajo para
 * absorber un borrado legítimo puntual sin flapping.
 *
 * Cómo actualizarlo: al añadir tests, recontá con
 *   cd web && node scripts/run-vitest.mjs   (el gate imprime cuántos corrieron)
 * y subí el número dejando el mismo margen. Si necesitás **bajarlo**, no lo
 * bajes: o borraste tests (justificalo en el PR y que lo revise un humano) o el
 * runner se está muriendo a medias, que es justo lo que este gate detecta.
 */
const MIN_TEST_FILES = 120;

/** Patrones de fallo de arranque del pool que vitest reporta con exit 0. */
// Deliberadamente NO incluye "Vitest caught N unhandled error": eso sí sale con
// exit != 0 y es un fallo real de test, no un no-ejecutado. Meterlo aquí haría
// que el gate diera el mensaje equivocado a quien tiene un test roto de verdad.
const PATRONES_POOL = [/Failed to start (forks|threads|vmThreads|vmForks) worker/i, /\[vitest-pool\]/i];

/**
 * `--expect-min=N` lo consume este script (no llega a vitest) y baja el mínimo
 * exigido para esta invocación. Es el escape para correr un subconjunto a mano
 * (`node scripts/run-vitest.mjs --expect-min=1 src/lib/foo.test.ts`).
 *
 * Es explícito a propósito: intentar adivinar si la invocación está filtrada
 * mirando los argumentos posicionales no funciona —el valor de un flag como
 * `--dir src/app` también es posicional— y adivinar de menos convierte el gate
 * en el mismo falso verde que viene a matar. Por defecto manda el ratchet.
 */
const argsCrudos = process.argv.slice(2);
const flagMinimo = argsCrudos.find((arg) => arg.startsWith("--expect-min="));
const argsVitest = argsCrudos.filter((arg) => arg !== flagMinimo);
const minimoEsperado = flagMinimo ? Number.parseInt(flagMinimo.split("=")[1], 10) : MIN_TEST_FILES;

if (!Number.isFinite(minimoEsperado) || minimoEsperado < 1) {
  process.stderr.write(`[web-test] --expect-min inválido: ${flagMinimo}\n`);
  process.exit(2);
}

const dirTemporal = mkdtempSync(join(tmpdir(), "tenderflow-vitest-"));
const ficheroInforme = join(dirTemporal, "vitest-report.json");

/**
 * `--reporter=default` mantiene la salida legible para quien mira la consola;
 * `--reporter=json` es lo que este script parsea. Con dos reporters, vitest
 * exige la forma `--outputFile.json=` para decir cuál va a fichero.
 */
const argv = [
  join(WEB_DIR, "node_modules", "vitest", "vitest.mjs"),
  "run",
  ...argsVitest,
  "--reporter=default",
  "--reporter=json",
  `--outputFile.json=${ficheroInforme}`,
];

let salidaCapturada = "";

const hijo = spawn(process.execPath, argv, {
  cwd: WEB_DIR,
  stdio: ["inherit", "pipe", "pipe"],
});

// Tee: la salida sigue viéndose en vivo y además la guardamos para escanearla.
for (const [flujo, destino] of [
  [hijo.stdout, process.stdout],
  [hijo.stderr, process.stderr],
]) {
  flujo.on("data", (chunk) => {
    salidaCapturada += chunk.toString();
    destino.write(chunk);
  });
}

hijo.on("error", (err) => {
  fallar([
    `No se pudo lanzar vitest: ${err.message}`,
    "Comprobá que web/node_modules está instalado (`cd web && npm ci`).",
  ]);
});

hijo.on("close", (codigoVitest) => {
  let informe = null;
  let errorLectura = null;
  try {
    informe = JSON.parse(readFileSync(ficheroInforme, "utf8"));
  } catch (err) {
    errorLectura = err.message;
  }
  limpiar();

  const erroresPool = PATRONES_POOL.filter((patron) => patron.test(salidaCapturada));

  const problemas = [];
  let ficherosEjecutados = 0;

  if (informe === null) {
    problemas.push(`vitest no dejó informe JSON legible en ${ficheroInforme} (${errorLectura}).`);
  } else {
    ficherosEjecutados = Array.isArray(informe.testResults)
      ? informe.testResults.length
      : (informe.numTotalTestSuites ?? 0);
    if (ficherosEjecutados < minimoEsperado) {
      problemas.push(
        `Solo se ejecutaron ${ficherosEjecutados} ficheros de test; se esperaban al menos ${minimoEsperado}.`,
      );
    }
    if ((informe.numTotalTests ?? 0) === 0) {
      problemas.push("No se ejecutó ni un solo caso de test (numTotalTests = 0).");
    }
  }

  if (erroresPool.length > 0) {
    problemas.push(
      "La salida contiene errores de arranque del pool de vitest " +
        "(`Failed to start … worker` / `[vitest-pool]`): parte de la suite no llegó a correr.",
    );
  }

  if (problemas.length === 0) {
    // La suite corrió entera: a partir de aquí manda vitest. Si devolvió != 0
    // es un test en rojo de verdad y su propia salida ya lo explica; el gate no
    // tiene nada que añadir y no debe pisar ese mensaje con el suyo.
    //
    // El recuento se imprime siempre: es el número con el que se actualiza el
    // ratchet, y tenerlo en el log de CI evita tener que adivinarlo.
    process.stdout.write(
      `\n[web-test] Suite ejecutada: ${ficherosEjecutados} ficheros, ` +
        `${informe?.numTotalTests ?? 0} casos (mínimo exigido: ${minimoEsperado}).\n`,
    );
    process.exit(codigoVitest);
  }

  fallar(problemas);
});

function limpiar() {
  try {
    rmSync(dirTemporal, { recursive: true, force: true });
  } catch {
    // Un temporal huérfano no justifica tumbar el gate.
  }
}

/**
 * Mensaje pensado para quien lo lea en CI: lo primero que tiene que entender es
 * que **sus tests no fallaron, la suite no llegó a ejecutarse**. Confundir una
 * cosa con la otra manda a la gente a depurar código que está bien.
 */
function fallar(problemas) {
  limpiar();
  const linea = "─".repeat(72);
  const texto = [
    "",
    linea,
    "LA SUITE DE TESTS DEL FRONTEND NO SE EJECUTÓ (esto NO es un test en rojo)",
    linea,
    "vitest terminó sin ejecutar lo que se esperaba. Que no veas tests fallando",
    "no significa que todo esté bien: significa que no se comprobó nada.",
    "",
    ...problemas.map((p) => `  · ${p}`),
    "",
    "Qué hacer:",
    "  1. Buscá arriba `Failed to start … worker` o `[vitest-pool]`. Si aparece,",
    "     vitest no pudo arrancar sus procesos (disco lento, poca RAM, antivirus,",
    "     runner de CI saturado). Reintentá con",
    "     `npm run test -- --pool=threads --no-file-parallelism`.",
    "  2. Si borraste ficheros de test a propósito, actualizá MIN_TEST_FILES en",
    "     web/scripts/run-vitest.mjs y explicá el motivo en el PR.",
    "  3. Si querías correr un subconjunto a mano, pedilo explícito:",
    "     `npm run test -- --expect-min=1 ruta/al/fichero.test.ts`.",
    "  4. NO relajes ni desactives este gate para pasar a verde: existe justo",
    "     porque `vitest run` devuelve exit 0 cuando no ejecuta nada.",
    linea,
    "",
  ].join("\n");
  process.stderr.write(texto);
  process.exit(1);
}
