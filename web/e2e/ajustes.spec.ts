import { expect, test } from "@playwright/test";

/**
 * Ajustes — el espacio que C7.5 creó sobre lo que C2 dejó en el backend.
 *
 * Las tres primeras vistas no tenían pantalla ninguna: `list_active_sessions`
 * existía desde siempre sin ruta, `api_key_tiers` desde `v28` sin lector, y las
 * preferencias nacieron en `v118` sin superficie. La cuarta, «datos y cuenta»,
 * vivía en `/mi-cuenta`, que este espacio absorbe.
 *
 * El criterio de aceptación del ítem es literal: **cambiar una preferencia y
 * verla persistida tras recargar**. Recargar es la mitad que importa — un
 * `PUT` que devuelve 200 y no escribe deja la pantalla correcta hasta que
 * alguien vuelve, y ese es exactamente el fallo que un test sin recarga no ve.
 */

test.describe("Ajustes", () => {
  test("la ruta heredada /mi-cuenta lleva a su vista dentro del espacio", async ({ page }) => {
    // Consolidar no elimina: el enlace guardado de alguien tiene que seguir
    // funcionando, y acabar donde ahora vive el contenido.
    await page.goto("/mi-cuenta");
    await expect(page).toHaveURL(/\/ajustes\?vista=cuenta/);
    await expect(page.getByRole("button", { name: /Descargar mis datos/ })).toBeVisible({
      timeout: 20_000,
    });
  });

  test("las cuatro vistas del espacio se abren", async ({ page }) => {
    await page.goto("/ajustes");
    await expect(page.locator("main#main-content")).toBeVisible({ timeout: 20_000 });

    for (const [vista, marca] of [
      ["sesiones", /Sesiones activas/],
      ["claves", /Nueva clave/],
      ["notificaciones", /Qué avisos quieres recibir/],
      ["cuenta", /Descargar mis datos/],
    ] as const) {
      await page.goto(`/ajustes?vista=${vista}`);
      await expect(page.getByText(marca).first()).toBeVisible({ timeout: 20_000 });
    }
  });

  test("una preferencia cambiada sigue ahí tras recargar", async ({ page }) => {
    await page.goto("/ajustes?vista=notificaciones");

    // El primer selector de la vista: el canal «En la aplicación» del primer
    // tipo de aviso. No se busca por un `tipo` concreto porque el catálogo lo
    // sirve el backend y fijarlo aquí duplicaría la lista que ADR-014 saca de
    // la UI a propósito.
    const selector = page.getByRole("combobox").first();
    await expect(selector).toBeVisible({ timeout: 20_000 });

    await selector.click();
    await page.getByRole("option", { name: "No avisar" }).click();
    await expect(selector).toContainText("No avisar");

    await page.reload();
    const trasRecargar = page.getByRole("combobox").first();
    await expect(trasRecargar).toContainText("No avisar", { timeout: 20_000 });
  });

  test("la sesión actual se marca y no se puede cerrar desde la lista", async ({ page }) => {
    // Cerrarla desde aquí sería un logout disfrazado de gestión, y ese botón ya
    // está en el menú de usuario donde la gente lo espera.
    await page.goto("/ajustes?vista=sesiones");
    await expect(page.getByText("Esta sesión").first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Cerrá sesión desde el menú").first()).toBeVisible();
  });
});
