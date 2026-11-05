/**
 * Respuestas de la API para los tests, sacadas de los fixtures de contrato.
 *
 * Los JSON de `test/fixtures/` los valida CI contra el OpenAPI real
 * (`scripts/check_contract_fixtures.py`), pero hasta 2026-11 ningún test los
 * importaba: cada test escribía a mano el cuerpo de la respuesta y podía
 * mandar un `user_id: "1"` donde la API manda `1`, o un `id` donde manda
 * `id_externo`, y el test pasaba igual. Con este helper el test parte del
 * cuerpo validado y solo cambia lo que su caso necesita.
 *
 * La ruta es una `ApiGetPath`, así que el tipo de la respuesta sale del
 * esquema generado: un `{ ...respuestaDeContrato(ruta), campo: valor }` con un
 * campo que la API no tiene no compila.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { ApiGetPath, ApiGetResult } from "@/lib/api-client";
import manifiesto from "./fixtures/manifest.json";

/**
 * Copia nueva del fixture de la respuesta 200 de `GET ruta`. Lanza si no hay
 * fixture para esa ruta: se añade a `fixtures/manifest.json` y CI lo valida.
 */
export function respuestaDeContrato<P extends ApiGetPath>(ruta: P): ApiGetResult<P> {
  const entrada = manifiesto.fixtures.find(
    (f) => f.method === "GET" && f.path === ruta && f.kind === "response" && f.status === "200",
  );
  if (!entrada) throw new Error(`No hay fixture de contrato para GET ${ruta} (test/fixtures/manifest.json)`);
  const texto = readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "fixtures", entrada.fixture), "utf8");
  return JSON.parse(texto) as ApiGetResult<P>;
}
