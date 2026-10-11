import { PRESUPUESTO_RECORRIDO_MS, test, expect } from "./cuenta-desechable";
import { SEED_LICITACION } from "./fixtures";

/**
 * Una regla de alerta, de la vista previa al borrado, en Mi Watchlist.
 *
 * Con cuenta desechable: una regla activa del usuario del seed le llenaría la
 * campana y la Agenda («señales») al resto de la suite.
 */

/** Sale en el título de un único expediente del seed: el que el Radar lista. */
const PALABRA = "ERP";

test("una regla por palabra clave enseña lo que casa, sobrevive a la recarga y se borra", async ({ page }) => {
  // CU-04
  test.setTimeout(PRESUPUESTO_RECORRIDO_MS);
  await page.goto("/mi-watchlist");
  await expect(page.getByRole("heading", { name: "Reglas (0)" })).toBeVisible();

  // ── Probarla antes de guardarla ──────────────────────────────────────────
  await page.getByRole("textbox", { name: "Palabra clave *" }).fill(PALABRA);
  const [vistaPrevia] = await Promise.all([
    page.waitForResponse(
      (candidata) =>
        candidata.url().includes("/api/v1/watchlist/rules/preview") && candidata.request().method() === "POST",
    ),
    page.getByRole("button", { name: "Ver cuántas alertas daría" }).click(),
  ]);
  expect(vistaPrevia.status(), "POST /watchlist/rules/preview").toBe(200);
  const { total } = (await vistaPrevia.json()) as { total: number };
  expect(total, `ningún expediente del seed contiene «${PALABRA}»`).toBeGreaterThan(0);
  await expect(page.getByText(`${total} licitación(es) coincidirían hoy`)).toBeVisible();

  // ── Guardarla ────────────────────────────────────────────────────────────
  const [alta] = await Promise.all([
    page.waitForResponse(
      (candidata) =>
        /\/api\/v1\/watchlist\/rules(\?|$)/.test(candidata.url()) && candidata.request().method() === "POST",
    ),
    page.getByRole("button", { name: "Añadir regla" }).click(),
  ]);
  expect(alta.status(), "POST /watchlist/rules").toBe(201);

  // Lo que casa es lo que contó la vista previa: la tarjeta de la regla lleva
  // la misma cifra, y la lista de abajo, el expediente.
  await expect(page.getByRole("heading", { name: "Reglas (1)" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: PALABRA, exact: true })).toBeVisible();
  await expect(page.getByText(`${total} coincidencias`, { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Resultados combinados" })).toBeVisible();
  const coincidencia = page.getByRole("link", { name: SEED_LICITACION.tituloRadar });
  await expect(coincidencia).toBeVisible();
  await expect(coincidencia).toHaveAttribute("href", `/detalle?lic=${SEED_LICITACION.radarId}`);

  // ── Es del servidor, no de la pestaña ────────────────────────────────────
  await page.reload();
  await expect(page.getByRole("heading", { name: "Reglas (1)" })).toBeVisible();
  await expect(page.getByRole("link", { name: SEED_LICITACION.tituloRadar })).toBeVisible();

  // ── Borrarla ─────────────────────────────────────────────────────────────
  const [baja] = await Promise.all([
    page.waitForResponse(
      (candidata) =>
        /\/api\/v1\/watchlist\/rules\/\d+/.test(candidata.url()) && candidata.request().method() === "DELETE",
    ),
    page.getByRole("button", { name: "Eliminar regla" }).click(),
  ]);
  expect(baja.ok(), `DELETE de la regla devolvió ${baja.status()}`).toBe(true);

  await expect(page.getByRole("heading", { name: "Reglas (0)" })).toBeVisible();
  await expect(page.getByText("No tienes reglas de seguimiento configuradas")).toBeVisible();
  // Sin reglas activas no hay nada que combinar: la sección entera se va.
  await expect(page.getByRole("heading", { name: "Resultados combinados" })).toHaveCount(0);

  await page.reload();
  await expect(page.getByRole("heading", { name: "Reglas (0)" })).toBeVisible();
});
