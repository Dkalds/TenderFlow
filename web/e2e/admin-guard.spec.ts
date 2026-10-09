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
 * (`?vista=flags` ya no es una vista propia: abre Administración.)
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
  // El aviso lo pone `AdminGuard` (web/src/components/admin-guard.tsx), que
  // envuelve el componente entero — no su JSX — para que las queries de admin
  // ni se disparen sin permisos. Antes había además una tarjeta con un texto
  // distinto ("Solo accesible...") dentro de `AdministracionContent`, pero esa
  // vivía por debajo de la guarda: nunca llegaba a montarse para un usuario
  // sin privilegios (la guarda cortaba antes) y sí se colaba, al revés, ante
  // un admin real — se quitó por muerta. Este test comprueba el único aviso
  // que de verdad se ve, con el texto que `AdminGuard` pinta hoy.
  test("la vista de administración avisa de que hace falta ser administrador", async ({
    page,
  }) => {
    await page.goto("/ops?vista=administracion");

    await expect(page.getByText(/solo está disponible para administradores/i).first()).toBeVisible(
      {
        timeout: 20000,
      },
    );
  });
});

test.describe("Sesión de administración", () => {
  test.use({ storageState: STORAGE_STATE_ADMIN });

  test("la vista de administración lista los usuarios reales", async ({ page }) => {
    await page.goto("/ops?vista=administracion");

    await expect(page.getByText(/solo está disponible para administradores/i)).toHaveCount(0);
    // El usuario demo existe en la BD sembrada: si la tabla no carga desde la
    // API, este texto no aparece.
    await expect(page.getByText(DEMO_USER.email).first()).toBeVisible({ timeout: 20000 });
  });

  test("el `?vista=flags` de antes abre Administración con sus feature flags", async ({ page }) => {
    // Feature flags fue una vista propia hasta 2026-10; hoy es una sección de
    // Administración. El `?vista=` viejo —el de un marcador, y el destino del
    // redirect de `/feature-flags`— tiene que seguir llegando a ella.
    await page.goto("/ops?vista=flags");

    await expect(page.getByText(/solo está disponible para administradores/i)).toHaveCount(0);
    await expect(page.getByRole("tab", { name: /Administración/ })).toHaveAttribute(
      "aria-selected",
      "true",
      { timeout: 20000 },
    );
    await expect(page.getByRole("heading", { name: "Feature flags" })).toBeVisible({ timeout: 20000 });
  });

  test("la vista de ejecuciones lista los pasos del cierre", async ({ page }) => {
    // De extremo a extremo contra la API real: `GET /admin/ejecuciones` devuelve
    // los pasos canónicos aunque la BD sembrada no tenga ninguna pasada, así
    // que la tabla no puede salir vacía. `ml_scoring` es el primero del cierre.
    await page.goto("/ops?vista=ejecuciones");

    await expect(page.getByRole("heading", { name: "Pasos del cierre" })).toBeVisible({ timeout: 20000 });
    await expect(page.getByText("ml_scoring").first()).toBeVisible();
  });
});
