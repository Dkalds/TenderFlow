import { test, expect } from "@playwright/test";
import { ID_INEXISTENTE, SEED_LICITACION } from "./fixtures";

/**
 * Permalink del panel de detalle: /detalle?lic=<id_externo>.
 *
 * El test anterior metía su única aserción real dentro de `if (!isOnLogin)`, y
 * como sin sesión todo redirigía al login, esa rama no se ejecutaba nunca:
 * quedaba un filtro de errores de consola que además descartaba 404 y 500.
 * Ahora el deep-link se abre con sesión y contra un id que existe en la BD, así
 * que se puede exigir que el panel muestre esa licitación.
 */

test("un permalink válido abre el detalle con los datos de esa licitación", async ({ page }) => {
  await page.goto(`/detalle?lic=${SEED_LICITACION.id}`);

  // El parámetro sobrevive al montaje (nuqs no lo descarta).
  await expect(page).toHaveURL(new RegExp(`lic=${SEED_LICITACION.id}`));
  // Y el contenido corresponde a ESA licitación, no a una cualquiera.
  await expect(page.getByText(SEED_LICITACION.titulo).first()).toBeVisible({
    timeout: 20000,
  });
});

test("un permalink inexistente no rompe la página", async ({ page }) => {
  const erroresJs: string[] = [];
  page.on("pageerror", (err) => erroresJs.push(err.message));

  await page.goto(`/detalle?lic=${ID_INEXISTENTE}`);

  await expect(page).toHaveURL(new RegExp(`lic=${ID_INEXISTENTE}`));
  await expect(page.locator("main").first()).toBeVisible();
  // El título de la licitación real no debe aparecer: sería señal de que el
  // panel ignora el parámetro y muestra la primera fila que encuentre.
  await expect(page.getByText(SEED_LICITACION.titulo)).toHaveCount(0);
  expect(erroresJs).toEqual([]);
});
