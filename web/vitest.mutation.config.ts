/**
 * La configuración de vitest que usa Stryker (`npm run test:mutation`): la de
 * siempre, con los tests acotados a un directorio.
 *
 * Por qué hace falta: para probar un mutante sólo cuentan los tests que
 * importan el fichero mutado, pero «importan» es transitivo.
 * `lib/filter-params.ts` lo importa `lib/filters.ts`, y a ése todas las
 * pantallas que leen el ámbito: sus tests relacionados son casi la suite
 * entera, y la pasada inicial de Stryker no termina en sus cinco minutos
 * (medido el 2026-10-11: «Initial test run timed out»). Acotado a `src/lib`,
 * cada módulo se mide contra los tests que de verdad lo ejercitan —el mismo
 * criterio que el mapeo explícito de `scripts/run_mutation_sample.py`— y un
 * superviviente señala el test unitario que falta, en vez de depender de que
 * una página lejana lo mate de rebote.
 *
 * No se usa la opción `dir` de vitest: cambia la base contra la que se
 * resuelve `include`, y el de `vitest.config.ts` empieza por `src/` (con
 * `dir: "src/lib"` busca en `src/lib/src/**` y no encuentra nada).
 *
 * Para mutar algo de fuera de `src/lib` hay que mover también esto, o no habrá
 * tests que lo cubran:
 *
 *   MUTATION_TESTS_DIR="src/app/(dashboard)/mi-perfil" \
 *     npm run test:mutation -- --mutate "src/app/(dashboard)/mi-perfil/_lib/reparto-pesos.ts"
 */
import { defineConfig } from "vitest/config";
import base from "./vitest.config";

const directorio = process.env.MUTATION_TESTS_DIR || "src/lib";
// Los grupos de rutas de Next llevan paréntesis, que en un glob son sintaxis.
const comoGlob = directorio.replace(/[()[\]{}!*?+@]/g, "\\$&");

export default defineConfig({
  ...base,
  test: {
    ...base.test,
    include: [`${comoGlob}/**/*.{test,spec}.{ts,tsx}`],
  },
});
