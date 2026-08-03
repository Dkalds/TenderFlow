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
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUTPUT = resolve(__dirname, "../src/generated/api.d.ts");
const OPENAPI_URL = "http://localhost:8080/api/openapi.json";

/** Ordena las claves de todo el objeto, como `json.dump(..., sort_keys=True)`. */
function ordenarClaves(valor) {
  if (Array.isArray(valor)) return valor.map(ordenarClaves);
  if (valor && typeof valor === "object") {
    return Object.fromEntries(
      Object.keys(valor)
        .sort()
        .map((clave) => [clave, ordenarClaves(valor[clave])])
    );
  }
  return valor;
}

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
    // openapi-typescript v7 devuelve un AST de TypeScript, no una cadena: hay
    // que pasarlo por `astToString`. La versión anterior de este script hacía
    // `JSON.stringify(output)` cuando no era string, así que **destruía**
    // api.d.ts dejándolo en una línea de basura. No se notaba porque en CI el
    // job `frontend` construye sin API viva y esta función sale antes por el
    // camino de "API not available"; se manifiesta en local, y en cualquier
    // job que levante la API antes del build (como el E2E).
    const { default: openapiTypescript, astToString, COMMENT_HEADER } = await import(
      "openapi-typescript"
    );

    // El artefacto canónico se genera desde `api/openapi.json`, que
    // `scripts/export_openapi.py` escribe con `sort_keys=True`. La API en vivo
    // sirve el spec en el orden natural de FastAPI, así que sin ordenar aquí
    // este script produciría un fichero equivalente pero distinto byte a byte
    // y el gate `codegen-drift` marcaría un drift que no existe.
    const output = await openapiTypescript(ordenarClaves(spec));
    const generado = typeof output === "string" ? output : astToString(output);
    const contenido = generado.startsWith("/**") ? generado : COMMENT_HEADER + generado;
    if (!contenido || contenido.trim().length === 0) {
      // Nunca sobreescribir con vacío: el archivo commiteado es mejor que nada.
      console.warn("[codegen] Generation produced empty output, keeping existing file");
      return;
    }
    writeFileSync(OUTPUT, contenido);
    console.log("[codegen] Generated " + OUTPUT);
  } catch (err) {
    // No bloquear el build si falla la generación
    console.warn("[codegen] Generation failed (non-fatal):", err.message);
  }
}

main();
