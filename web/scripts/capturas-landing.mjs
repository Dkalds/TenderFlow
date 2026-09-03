#!/usr/bin/env node
/**
 * Lanza la regeneración de las capturas de la landing.
 *
 * Existe por la misma razón que `run-vitest.mjs`: `CAPTURAS=1 playwright ...`
 * no es portable — funciona en un shell POSIX y falla en `cmd.exe`, que es
 * donde npm ejecuta los scripts en Windows. Un wrapper de diez líneas evita
 * añadir `cross-env` como dependencia sólo para esto.
 *
 * El trabajo lo hace `e2e/capturas-landing.spec.ts`; aquí sólo se pone la
 * variable que lo desbloquea y se propaga el código de salida.
 */
import { spawnSync } from "node:child_process";

const resultado = spawnSync(
  "npx",
  ["playwright", "test", "capturas-landing", "--project=chromium", ...process.argv.slice(2)],
  {
    stdio: "inherit",
    shell: true,
    env: { ...process.env, CAPTURAS: "1" },
  },
);

process.exit(resultado.status ?? 1);
