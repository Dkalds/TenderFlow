import { test, expect, type Page } from "@playwright/test";

/**
 * El Investigador de punta a punta: una frase escrita como se habla, lo que se
 * entendió de ella, la vuelta a «el texto tal cual» y la alerta con lo mismo.
 *
 * Solo lee: la regla se deja en el formulario sin guardar, así que basta con
 * la sesión de demo (guardarla es `recorrido-alerta.spec.ts`).
 */

/** Sin tildes a propósito: el seed escribe «auditoría», y tiene que casar. */
const FRASE = "auditoria de sistemas del Ayuntamiento de Madrid";
/** SEED-2026-004, del Ayuntamiento de Madrid. */
const DEL_ORGANO = "Servicios de ciberseguridad y auditoría de sistemas";
/** SEED-2026-013: casa con el texto, pero es del Ministerio de Defensa. */
const DE_OTRO_ORGANO = "Auditoría y certificación ISO 27001 de sistemas de información";

async function buscar(page: Page, frase: string) {
  const [respuesta] = await Promise.all([
    page.waitForResponse(
      (candidata) => candidata.url().includes("/api/v1/search/semantic") && candidata.request().method() === "POST",
    ),
    (async () => {
      // El formulario del Investigador: la barra de arriba tiene otro «Buscar» (⌘K).
      const formulario = page.getByRole("search");
      await formulario.getByRole("textbox", { name: "Busca o pregunta" }).fill(frase);
      await formulario.getByRole("button", { name: "Buscar", exact: true }).click();
    })(),
  ]);
  expect(respuesta.status(), "POST /search/semantic").toBe(200);
}

test("una frase con órgano filtra, se puede buscar tal cual y se convierte en alerta", async ({ page }) => {
  // CU-23
  await page.goto("/investigador");
  await buscar(page, FRASE);

  // ── Lo que se entendió ───────────────────────────────────────────────────
  await expect(page.getByText("Órgano: Ayuntamiento de Madrid")).toBeVisible();
  // El título llega troceado en tramos resaltados: se busca por el nombre
  // accesible del enlace, que los une.
  await expect(page.getByRole("link", { name: DEL_ORGANO })).toBeVisible();
  await expect(page.getByRole("link", { name: DE_OTRO_ORGANO })).toHaveCount(0);

  // ── El texto tal cual: sin el filtro, sale el del otro órgano ───────────
  const [talCual] = await Promise.all([
    page.waitForResponse((candidata) => candidata.url().includes("/api/v1/search/semantic")),
    page.getByRole("button", { name: "Buscar el texto tal cual" }).click(),
  ]);
  expect(talCual.status()).toBe(200);
  await expect(page.getByRole("link", { name: DE_OTRO_ORGANO })).toBeVisible();
  await expect(page.getByRole("link", { name: DEL_ORGANO })).toBeVisible();

  // ── La alerta lleva lo entendido ─────────────────────────────────────────
  // La búsqueda interpretada ya está en caché: volver a ella no pide nada.
  await page.getByRole("button", { name: "Volver a leerlos" }).click();
  await expect(page.getByText("Órgano: Ayuntamiento de Madrid")).toBeVisible();
  await expect(page.getByRole("link", { name: DE_OTRO_ORGANO })).toHaveCount(0);
  await page.getByRole("link", { name: "Crear alerta" }).click();
  await expect(page).toHaveURL(/\/mi-watchlist\?prefill=/);
  await expect(page.getByRole("textbox", { name: "Palabra clave *" })).toHaveValue("auditoria sistemas");
  await expect(page.getByText("Además filtra por")).toBeVisible();
  await expect(page.getByText("Órgano: Ayuntamiento de Madrid")).toBeVisible();
});
