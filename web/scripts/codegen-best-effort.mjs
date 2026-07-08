/**
 * codegen-best-effort.mjs
 *
 * Genera src/generated/api.d.ts a partir de la API local si está disponible.
 * Usa Node puro (sin shell POSIX) para funcionar en Windows, Linux y macOS.
 *
 * Comportamiento:
 *   - Si la API responde en http://localhost:8080/api/openapi.json → genera el tipo.
 *   - Si la API no está disponible → avisa y sale con código 0 (no bloquea el build).
 *
 * Reemplaza el one-liner con `2>/dev/null || true` que rompe en Windows.
 */

import { writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUTPUT = resolve(__dirname, "../src/generated/api.d.ts");
const OPENAPI_URL = "http://localhost:8080/api/openapi.json";

async function main() {
  let spec;
  try {
    const response = await fetch(OPENAPI_URL, { signal: AbortSignal.timeout(5000) });
    if (!response.ok) {
      console.log("[codegen] API not available (HTTP " + response.status + "), skipping");
      process.exit(0);
    }
    spec = await response.json();
  } catch {
    console.log("[codegen] API not available, skipping");
    process.exit(0);
  }

  try {
    // openapi-typescript expone una función default en ESM
    const require = createRequire(import.meta.url);
    let openapiTypescript;
    try {
      // v7+ ESM
      const mod = await import("openapi-typescript");
      openapiTypescript = mod.default ?? mod;
    } catch {
      // fallback CJS
      openapiTypescript = require("openapi-typescript");
    }

    const output = await openapiTypescript(spec);
    writeFileSync(OUTPUT, typeof output === "string" ? output : JSON.stringify(output));
    console.log("[codegen] Generated " + OUTPUT);
  } catch (err) {
    // No bloquear el build si falla la generación
    console.warn("[codegen] Generation failed (non-fatal):", err.message);
  }
}

main();
