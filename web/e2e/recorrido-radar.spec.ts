import type { Page } from "@playwright/test";
import { PRESUPUESTO_RECORRIDO_MS, test, expect } from "./cuenta-desechable";
import { SEED_LICITACION } from "./fixtures";
import { filaDelRadar, seleccionarFilaDelRadar } from "./radar-fila";

/**
 * Descartar una señal del Radar y recuperarla.
 *
 * Con cuenta desechable: el descarte es del usuario, y `navigation.spec.ts`,
 * `critical-workflows.spec.ts` y `responsive.spec.ts` buscan esta misma fila en
 * la bandeja del usuario del seed. Un fallo a medio recorrido la dejaría
 * descartada para todos ellos.
 */

const TITULO = SEED_LICITACION.tituloRadar;
const ID = SEED_LICITACION.radarId;

test("una señal descartada sale de la bandeja, sigue descartada al recargar y se recupera", async ({ page }) => {
  // CU-10
  test.setTimeout(PRESUPUESTO_RECORRIDO_MS);
  await page.goto("/radar");
  const bandejas = page.getByRole("group", { name: "Bandejas" });

  // ── Descartar ────────────────────────────────────────────────────────────
  const fila = await seleccionarFilaDelRadar(page, TITULO);
  const [descarte] = await Promise.all([
    page.waitForResponse(
      (candidata) =>
        /\/api\/v1\/radar\/dismissals(\?|$)/.test(candidata.url()) && candidata.request().method() === "POST",
    ),
    fila.getByRole("button", { name: `Descartar ${TITULO}` }).click(),
  ]);
  // El estado, y no solo que la fila se vaya: la pantalla la quita antes de
  // que el servidor conteste, así que un 4xx también la habría hecho
  // desaparecer un instante.
  expect(descarte.ok(), `POST /radar/dismissals devolvió ${descarte.status()}`).toBe(true);
  await expect(filaDelRadar(page, TITULO)).toHaveCount(0);
  await expect(bandejas.getByRole("button", { name: /^Descartadas\s*1$/ })).toBeVisible();

  // ── Sigue descartada al recargar: el descarte es del servidor ────────────
  await page.reload();
  // Primero que la bandeja haya cargado —otra fila del seed está—; si no, la
  // ausencia de la descartada se cumpliría sobre una lista aún vacía.
  await expect(filaDelRadar(page, SEED_LICITACION.titulo)).toBeVisible({ timeout: 20_000 });
  await expect(filaDelRadar(page, TITULO)).toHaveCount(0);
  expect(await descartadas(page)).toContain(ID);

  // Donde sí está es en su bandeja.
  await bandejas.getByRole("button", { name: /^Descartadas\s*1$/ }).click();
  await expect(filaDelRadar(page, TITULO)).toBeVisible();

  // ── Recuperarla ──────────────────────────────────────────────────────────
  // Con el botón de la barra y no con el «Deshacer» del aviso: el aviso se va
  // solo a los pocos segundos, y un test que dependa de llegar a tiempo falla
  // el día que el runner va lento.
  const [restauracion] = await Promise.all([
    page.waitForResponse(
      (candidata) =>
        candidata.url().includes(`/api/v1/radar/dismissals/${ID}`) && candidata.request().method() === "DELETE",
    ),
    page.getByRole("button", { name: "Restaurar 1 descartada" }).click(),
  ]);
  expect(restauracion.ok(), `DELETE del descarte devolvió ${restauracion.status()}`).toBe(true);
  await expect(bandejas.getByRole("button", { name: /^Descartadas\s*0$/ })).toBeVisible();

  await bandejas.getByRole("button", { name: /^Bandeja\b/ }).click();
  await expect(filaDelRadar(page, TITULO)).toBeVisible();

  await page.reload();
  await expect(filaDelRadar(page, TITULO)).toBeVisible({ timeout: 20_000 });
  expect(await descartadas(page)).not.toContain(ID);
});

/** Lo que el servidor tiene descartado para esta cuenta. */
async function descartadas(page: Page): Promise<string[]> {
  const respuesta = await page.request.get("/api/v1/radar/dismissals");
  expect(respuesta.ok(), `GET /radar/dismissals devolvió ${respuesta.status()}`).toBe(true);
  return ((await respuesta.json()) as { ids: string[] }).ids;
}
