import { test, expect } from "@playwright/test";
import { DEMO_USER, STORAGE_STATE_ADMIN } from "./fixtures";

/**
 * Protección de la administración, en sus tres estados.
 *
 * El cuarto test anterior ("shows access restricted for non-admin users")
 * dependía del botón de dev-login, que solo se renderiza con
 * `NODE_ENV=development`: contra un build de producción la condición era falsa
 * y el cuerpo no llegaba a ejecutarse. Además terminaba en
 * `expect(body).toBeVisible()`, que no comprueba nada. Los otros tres llevaban
 * `.catch(() => {})` en el `waitForURL`, así que un fallo de redirección solo
 * se detectaba de rebote.
 *
 * Las rutas heredadas (`/administracion`, `/feature-flags`,
 * `/active-learning`) hoy redirigen al espacio Ops con su vista; ese redirect
 * lo cubre navigation.spec.ts. Aquí se prueba quién puede ver el contenido.
 */

const VISTAS_ADMIN = [
  { ruta: "/ops?vista=administracion", legacy: "/administracion" },
  { ruta: "/ops?vista=flags", legacy: "/feature-flags" },
  { ruta: "/ops?vista=etiquetado", legacy: "/active-learning" },
];

test.describe("Sin sesión", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  for (const { legacy } of VISTAS_ADMIN) {
    test(`${legacy} redirige a /login`, async ({ page }) => {
      await page.goto(legacy);
      // Sin `.catch(() => {})`: si no redirige, el test debe fallar aquí.
      await page.waitForURL(/\/login/, { timeout: 15000 });
      expect(page.url()).toContain("/login");
    });
  }
});

test.describe("Sesión sin privilegios de administración", () => {
  // Solo la vista de administración declara el aviso de privilegios; las de
  // flags y etiquetado se limitan a no traer datos. Se prueba la que sí lo
  // dice en vez de aflojar la aserción para que valga en las tres.
  test("la vista de administración avisa de que hace falta ser administrador", async ({
    page,
  }) => {
    await page.goto("/ops?vista=administracion");

    await expect(page.getByText(/solo accesible para administradores/i).first()).toBeVisible({
      timeout: 20000,
    });
  });
});

test.describe("Sesión de administración", () => {
  test.use({ storageState: STORAGE_STATE_ADMIN });

  test("la vista de administración lista los usuarios reales", async ({ page }) => {
    await page.goto("/ops?vista=administracion");

    await expect(page.getByText(/solo accesible para administradores/i)).toHaveCount(0);
    // El usuario demo existe en la BD sembrada: si la tabla no carga desde la
    // API, este texto no aparece.
    await expect(page.getByText(DEMO_USER.email).first()).toBeVisible({ timeout: 20000 });
  });

  test("la vista de feature flags carga su panel", async ({ page }) => {
    await page.goto("/ops?vista=flags");

    await expect(page.getByText(/solo accesible para administradores/i)).toHaveCount(0);
    await expect(page.locator("main").first()).not.toBeEmpty();
  });
});
