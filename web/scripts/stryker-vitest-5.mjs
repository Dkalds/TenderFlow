/**
 * stryker-vitest-5.mjs
 *
 * Adaptador del runner de vitest de Stryker para vitest 5. Registra el runner
 * `vitest-5`, que es el oficial (`@stryker-mutator/vitest-runner`) con una
 * corrección y una guarda.
 *
 * Por qué existe: `@stryker-mutator/vitest-runner@10.0.0` declara
 * `vitest >=2.0.0` y se instala sin forzar nada, pero con vitest 5 **no mata
 * ningún mutante** y lo dice en verde. Para probar un mutante, el runner lanza
 * sólo los tests que pasan por su línea, y los elige con `testNamePattern`: un
 * patrón hecho con el nombre completo del test, que él compone uniendo
 * `describe` e `it` con un espacio («slugificar pliega los diacríticos»).
 * Vitest 5 compara ese patrón con el nombre unido por « > » («slugificar >
 * pliega los diacríticos»), así que ningún test dentro de un `describe` casa:
 * el mutante se «prueba» contra cero tests, sobrevive, y el informe sale con
 * una puntuación ridícula sin un solo error. Medido el 2026-10-11 sobre
 * `safe-redirect.ts` y `slug.ts`, los mismos 78 mutantes: sin adaptador, 74
 * supervivientes, puntuación 3,85 % y «Ran 0.26 tests per mutant»; con él, 9
 * supervivientes, 87,18 % y 6,17 tests por mutante.
 *
 * Se comprueba a mano en un minuto:
 *
 *   npx vitest run src/lib/__tests__/slug.test.ts -t "slugificar pliega"     # 18 skipped
 *   npx vitest run src/lib/__tests__/slug.test.ts -t "slugificar > pliega"   # 1 passed
 *
 * Qué hace:
 *
 *   1. **La corrección.** Intercepta el patrón que el runner asigna a cada
 *      proyecto y hace que cada espacio case también con « > ». El patrón
 *      resultante acepta el nombre en las dos formas, así que sigue valiendo
 *      si una versión posterior de vitest o del runner cambia de separador.
 *   2. **La guarda.** Si a un mutante le correspondían tests y no se ejecutó
 *      ninguno, no se da por superviviente: sale como error, y el reporter
 *      `guarda-vitest-5` cierra la ejecución con un aviso y código 1. Es el
 *      mismo criterio que `run-vitest.mjs`: «no se ejecutó nada» no puede
 *      pasar por un resultado. Comprobado desactivando la corrección: 33 de
 *      los 35 mutantes de `safe-redirect.ts` salen como error y el comando
 *      falla, en vez de un informe con 33 supervivientes.
 *
 * Cuándo borrarlo: cuando el runner oficial componga los nombres como vitest.
 * Para saberlo, poné `testRunner: "vitest"` y `plugins:
 * ["@stryker-mutator/vitest-runner"]` en `stryker.config.mjs` y corré la
 * muestra: si «tests per mutant» deja de rondar el cero y la puntuación se
 * parece a la de ahora, este fichero sobra.
 *
 * No importa `@stryker-mutator/api` (dependencia transitiva): envuelve la
 * fábrica que exporta el propio runner, y los dos valores de ese paquete que
 * necesita (`"error"` y `"Reporter"`) van escritos con su nombre al lado.
 */

import { strykerPlugins as pluginsOficiales, strykerValidationSchema } from "@stryker-mutator/vitest-runner";

const oficial = pluginsOficiales.find((plugin) => plugin.name === "vitest");
if (!oficial || typeof oficial.factory !== "function") {
  throw new Error(
    "[stryker-vitest-5] @stryker-mutator/vitest-runner ya no exporta el runner «vitest» como fábrica: " +
      "este adaptador se escribió para la 10.0.0 y hay que revisarlo (o borrarlo).",
  );
}

/** Marca de los mutantes que la guarda dejó sin probar; el reporter la busca. */
const MARCA = "[stryker-vitest-5]";

/** El separador con el que vitest 5 une `describe` e `it` en el nombre completo. */
const SEPARADOR_VITEST = " > ";

/**
 * El mismo patrón, aceptando en cada espacio el separador de vitest.
 *
 * El runner escapa el nombre antes de hacer la expresión regular, pero un
 * espacio no es un metacarácter y llega tal cual a `source`: se puede
 * sustituir sin deshacer el escapado. Acepta de más —un espacio dentro del
 * nombre de un test también casa con « > »—, lo que como mucho lanza algún
 * test extra, nunca deja uno fuera.
 */
export function patronParaVitest5(patron) {
  if (!(patron instanceof RegExp)) return patron;
  return new RegExp(patron.source.replaceAll(" ", `(?:${SEPARADOR_VITEST}| )`), patron.flags);
}

function adaptar(runner) {
  const initOficial = runner.init.bind(runner);
  runner.init = async () => {
    await initOficial();
    for (const proyecto of runner.ctx.projects) {
      let patron = proyecto.config.testNamePattern;
      Object.defineProperty(proyecto.config, "testNamePattern", {
        configurable: true,
        enumerable: true,
        get: () => patron,
        set: (valor) => {
          patron = patronParaVitest5(valor);
        },
      });
    }
  };

  const mutantRunOficial = runner.mutantRun.bind(runner);
  runner.mutantRun = async (opciones) => {
    const resultado = await mutantRunOficial(opciones);
    const habiaTests = (opciones.testFilter?.length ?? 0) > 0;
    // "survived" es el valor de `MutantRunStatus.Survived` en @stryker-mutator/api.
    if (habiaTests && resultado.status === "survived" && resultado.nrOfTests === 0) {
      // Un resultado de error y no una excepción: si el runner lanza, Stryker
      // lo da por caído y lo reinicia dos veces por mutante antes de rendirse.
      // "error" es `MutantRunStatus.Error`.
      return {
        status: "error",
        errorMessage:
          `${MARCA} Al mutante ${opciones.activeMutant.id} le correspondían ` +
          `${opciones.testFilter.length} tests y no se ejecutó ninguno.`,
      };
    }
    return resultado;
  };
  return runner;
}

function fabricaVitest5(...dependencias) {
  return adaptar(oficial.factory(...dependencias));
}
// Las mismas dependencias que pide la fábrica oficial al inyector de Stryker.
fabricaVitest5.inject = oficial.factory.inject;

/**
 * La otra mitad de la guarda, en el proceso principal: los runners viven en
 * procesos hijos y lo más que pueden hacer es marcar su mutante. Sin esto la
 * ejecución terminaría en 0 con una tabla que cuenta los errores en una
 * columna aparte y no los descuenta de la puntuación (33 errores y 2 muertos
 * salían como «100 %»).
 */
function fabricaGuarda() {
  return {
    onMutationTestReportReady(informe) {
      const sinProbar = Object.values(informe.files)
        .flatMap((fichero) => fichero.mutants)
        .filter((mutante) => mutante.statusReason?.includes(MARCA));
      if (sinProbar.length === 0) return;

      process.exitCode = 1;
      const linea = "─".repeat(72);
      process.stderr.write(
        [
          "",
          linea,
          "EL INFORME DE MUTACIÓN NO VALE (esto NO son mutantes supervivientes)",
          linea,
          `A ${sinProbar.length} mutantes les correspondían tests y no se ejecutó ninguno.`,
          "El runner elige los tests de cada mutante por su nombre, y el patrón que",
          "construye no casa con el nombre que compone esta versión de vitest. La",
          "puntuación de arriba no los cuenta: ignorala.",
          "",
          "Qué mirar: web/scripts/stryker-vitest-5.mjs (cabecera) y, a mano,",
          '  npx vitest run src/lib/__tests__/slug.test.ts -t "slugificar > pliega"',
          "que tiene que ejecutar un test y saltarse el resto.",
          linea,
          "",
        ].join("\n"),
      );
    },
  };
}
fabricaGuarda.inject = [];

export const strykerPlugins = [
  { ...oficial, name: "vitest-5", factory: fabricaVitest5 },
  // "Reporter" es `PluginKind.Reporter`.
  { kind: "Reporter", name: "guarda-vitest-5", factory: fabricaGuarda },
];
// Sin esto Stryker no conocería la sección `vitest` de la configuración.
export { strykerValidationSchema };
