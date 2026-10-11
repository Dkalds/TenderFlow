/**
 * Mutation testing del frontend (Stryker + vitest), a demanda.
 *
 * La cobertura dice qué líneas ejecutan los tests; no dice si alguna aserción
 * las vigila. Stryker rompe el código a propósito —cambia un operador, una
 * condición, una constante— y vuelve a correr los tests que pasan por ahí. Un
 * mutante **muerto** es un test que hizo su trabajo; uno **superviviente** es
 * código que puede romperse sin que nadie se entere.
 *
 * Es un **informe, no una puerta**: mismo criterio que `make mutation-sample`
 * en el backend (`scripts/run_mutation_sample.py`). Un superviviente puede ser
 * «falta un test» o «esa mutación es equivalente y da igual», y distinguirlo
 * pide criterio. Por eso no hay `thresholds.break`, no corre en CI y el
 * comando termina en 0 aunque sobrevivan mutantes.
 *
 * Uso (desde `web/`):
 *
 *   npm run test:mutation                                        # la muestra de abajo
 *   npm run test:mutation -- --mutate src/lib/periodo.ts         # un fichero
 *   npm run test:mutation -- --mutate "src/lib/slug.ts,src/lib/cobertura.ts"
 *   npm run test:mutation -- --mutate "src/lib/utils.ts:290-303" # un rango de líneas
 *
 * El informe queda en `reports/mutation/` (`mutation.html` para leerlo,
 * `mutation.json` para procesarlo) y los supervivientes salen también por la
 * consola. Ni el informe ni el directorio de trabajo (`.stryker-tmp/`) se
 * versionan.
 */

/**
 * La muestra por defecto: módulos pequeños de `src/lib`, sin efectos y con
 * tests propios, donde un superviviente señala un test que falta y no un
 * montaje que no se hizo. Mutar todo `src/lib` de una vez tarda decenas de
 * minutos y devuelve un informe que nadie lee entero.
 *
 * `src/lib/utils.ts` no está aquí a propósito: lo importa casi todo
 * `src/lib`, así que sus tests «relacionados» son los de la carpeta entera, y
 * tiene cientos de mutantes. Para mutarlo conviene acotar por líneas, como en
 * el último ejemplo de arriba.
 *
 * Los tests que juzgan a los mutantes son los de `src/lib` (ver
 * `vitest.mutation.config.ts`). Para mutar algo de fuera hay que mover también
 * eso:
 *
 *   MUTATION_TESTS_DIR="src/app/(dashboard)/mi-perfil" \
 *     npm run test:mutation -- --mutate "src/app/(dashboard)/mi-perfil/_lib/reparto-pesos.ts"
 */
const MUESTRA = [
  "src/lib/safe-redirect.ts",
  "src/lib/slug.ts",
  "src/lib/paginacion-hubs.ts",
  "src/lib/filter-params.ts",
];

/** @type {import('@stryker-mutator/api/core').PartialStrykerOptions} */
const config = {
  // `vitest-5` y no `vitest`: el runner oficial se instala con vitest 5 pero no
  // mata ningún mutante (elige los tests por un nombre que vitest 5 ya no
  // compone igual). El adaptador lo corrige y falla si vuelve a pasar; el
  // porqué y cuándo retirarlo, en su cabecera.
  testRunner: "vitest-5",
  plugins: ["./scripts/stryker-vitest-5.mjs"],
  mutate: MUESTRA,
  // Cada proceso es un vitest entero con su jsdom. El valor por defecto (uno
  // por núcleo menos uno) arrancó 23 en la máquina de desarrollo y tardó más
  // en levantarlos que en probar los mutantes; con `--concurrency N` se cambia.
  concurrency: 4,

  vitest: {
    // La configuración de siempre con los tests acotados a `src/lib` (o a
    // `MUTATION_TESTS_DIR`): el porqué, en la cabecera de ese fichero.
    configFile: "vitest.mutation.config.ts",
    // De esos, sólo los que importan (directa o indirectamente) lo que se muta.
    related: true,
  },
  // Cada mutante corre sólo contra los tests que pasan por su línea.
  coverageAnalysis: "perTest",

  // `guarda-vitest-5` no pinta nada salvo que el adaptador detecte mutantes sin
  // probar; entonces avisa y hace fallar el comando.
  reporters: ["clear-text", "progress", "html", "json", "guarda-vitest-5"],
  htmlReporter: { fileName: "reports/mutation/mutation.html" },
  jsonReporter: { fileName: "reports/mutation/mutation.json" },
  // Los colores de la tabla, nada más. `break: null` es lo que lo mantiene
  // como informe: con un número aquí, el comando fallaría por debajo de él.
  thresholds: { high: 80, low: 60, break: null },

  // Stryker trabaja sobre una copia del proyecto. Lo que no hace falta para
  // correr vitest no se copia: builds, informes y los E2E de Playwright.
  tempDirName: ".stryker-tmp",
  ignorePatterns: [
    ".next",
    ".vercel",
    "coverage",
    "reports",
    "e2e",
    "playwright-report",
    "test-results",
    "blob-report",
  ],
};

export default config;
