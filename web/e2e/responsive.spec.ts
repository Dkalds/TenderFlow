import { test, expect } from "@playwright/test";

/**
 * Navegación móvil real (cierra el [P1] de docs/IMPROVEMENT_BACKLOG.md).
 *
 * Los dos tests anteriores solo afirmaban `expect(body).toBeVisible()`. El
 * primero llegaba a construir un localizador del hamburguesa con tres
 * estrategias encadenadas y **nunca lo usaba** — el prefijo `_` existía para
 * callar al linter. Es decir: la única cobertura declarada de la experiencia
 * móvil pasaba con la navegación completamente rota, y por debajo de `md` la
 * sidebar es `hidden md:flex`, así que el drawer es la única forma de cambiar
 * de sección.
 *
 * Estos tests fallan si se elimina el drawer: sin `.or()`, sin `if`, sin
 * `.catch()`.
 */

const MOVIL = { width: 375, height: 812 };
const ESCRITORIO = { width: 1440, height: 900 };

test.describe("Móvil (375×812)", () => {
  test.use({ viewport: MOVIL });

  test("el drawer es la vía de navegación y abre con enlaces utilizables", async ({ page }) => {
    await page.goto("/resumen");

    // El rail de espacios (la navegación de escritorio) es `md:flex`: por
    // debajo de ese ancho no existe, y el drawer es la única alternativa.
    await expect(page.getByRole("navigation", { name: "Espacios" })).toBeHidden();

    const hamburguesa = page.getByRole("button", { name: "Abrir navegación" });
    await expect(hamburguesa).toBeVisible();

    await hamburguesa.click();

    const drawer = page.getByRole("dialog");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("navigation", { name: /navegación móvil/i })).toBeVisible();
  });

  test("navegar desde el drawer cambia de página y lo cierra", async ({ page }) => {
    await page.goto("/resumen");
    await page.getByRole("button", { name: "Abrir navegación" }).click();

    const drawer = page.getByRole("dialog");
    // Un destino concreto, no "algún enlace": si el menú se queda vacío o deja
    // de navegar, el test tiene que caer.
    await drawer.getByRole("link", { name: /Radar/ }).first().click();

    await expect(page).toHaveURL(/\/radar/);
    await expect(drawer).toBeHidden();
  });
});

test.describe("Escritorio (1440×900)", () => {
  test.use({ viewport: ESCRITORIO });

  test("el rail de espacios sustituye al hamburguesa", async ({ page }) => {
    await page.goto("/resumen");

    await expect(page.getByRole("navigation", { name: "Espacios" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Abrir navegación" })).toBeHidden();
  });
});
