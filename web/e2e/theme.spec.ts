import { test, expect } from "@playwright/test";

/**
 * Conmutador de tema.
 *
 * El test anterior envolvía todo su cuerpo en `if (await themeToggle.count() >
 * 0)`. Como sin sesión /resumen redirigía al login, que no tiene conmutador, la
 * condición era falsa siempre y el test pasaba sin ejecutar una sola aserción.
 * Con sesión el botón existe, así que aquí no hay condicional.
 */

test("alterna claro/oscuro y la elección sobrevive a una recarga", async ({ page }) => {
  await page.goto("/resumen");

  // El conmutador vive dentro del menú de cuenta del rail de consola, no como
  // botón suelto: hay que abrirlo primero.
  await page.getByRole("button", { name: "Menú de cuenta" }).click();
  const conmutador = page.getByRole("menuitem", { name: /modo (claro|oscuro)/i });
  await expect(conmutador).toBeVisible();

  const html = page.locator("html");
  const eraOscuro = (await html.getAttribute("class"))?.includes("dark") ?? false;

  await conmutador.click();
  if (eraOscuro) {
    await expect(html).not.toHaveClass(/dark/);
  } else {
    await expect(html).toHaveClass(/dark/);
  }

  // La preferencia se guarda (next-themes → localStorage): tras recargar sigue
  // aplicada. Sin esta comprobación, un fallo de persistencia pasaría
  // desapercibido porque en la misma vista todo parece correcto.
  await page.reload();
  if (eraOscuro) {
    await expect(html).not.toHaveClass(/dark/);
  } else {
    await expect(html).toHaveClass(/dark/);
  }
});
