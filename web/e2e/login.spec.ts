import { test, expect } from "@playwright/test";
import { DEMO_USER } from "./fixtures";

/**
 * El login se prueba sin sesión previa: estos specs vacían el storageState que
 * el proyecto inyecta por defecto.
 *
 * Se fueron dos tests que no podían fallar: uno afirmaba
 * `expect(count).toBeGreaterThanOrEqual(0)` sobre el botón de Google (cierto
 * para cualquier número) y otro rellenaba credenciales, esperaba dos segundos
 * y comprobaba que el `body` seguía visible. En su lugar hay un login real y
 * un fallo real.
 */

test.use({ storageState: { cookies: [], origins: [] } });

test.describe("Formulario de acceso", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    // El build de producción sirve HTML antes de hidratar: sin esta espera,
    // Playwright puede pulsar "Iniciar sesión" mientras el `onSubmit` de React
    // todavía no está enganchado, el formulario se envía de forma nativa y la
    // página acaba en `/login?` en vez de ejecutar el handler.
    await page.waitForLoadState("networkidle");
  });

  test("muestra los campos de acceso", async ({ page }) => {
    await expect(page.getByLabel(/email|correo/i)).toBeVisible();
    await expect(page.locator("#password")).toBeVisible();
    await expect(page.getByRole("button", { name: /^Iniciar/i })).toBeVisible();
  });

  test("credenciales válidas dejan sesión iniciada", async ({ page, context }) => {
    await page.getByLabel(/email|correo/i).fill(DEMO_USER.email);
    await page.locator("#password").fill(DEMO_USER.password);
    await page.getByRole("button", { name: /^Iniciar/i }).click();

    await expect(page).toHaveURL(/\/resumen/, { timeout: 20000 });

    // La cookie de sesión es opaca y httpOnly: se comprueba en el contexto,
    // no en `document.cookie`. Sin ella el resto de la aplicación es
    // inaccesible, así que es la aserción que importa.
    const cookies = await context.cookies();
    expect(cookies.map((c) => c.name)).toContain("session");
    expect(cookies.map((c) => c.name)).toContain("csrf_token");
  });

  test("una contraseña incorrecta muestra el error y no navega", async ({ page }) => {
    await page.getByLabel(/email|correo/i).fill(DEMO_USER.email);
    await page.locator("#password").fill("contraseña-incorrecta");
    await page.getByRole("button", { name: /^Iniciar/i }).click();

    // Se busca el mensaje que ve el usuario, no un rol ARIA concreto: si el
    // texto desaparece, da igual que el contenedor siga ahí.
    await expect(page.getByText(/credenciales incorrectas|demasiados intentos/i)).toBeVisible({
      timeout: 15000,
    });
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("Alta de cuenta", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
  });

  test("la pestaña de registro revela el campo de confirmación", async ({ page }) => {
    await expect(page.locator("#confirm-password")).toHaveCount(0);
    await page.getByRole("tab", { name: /crear cuenta|sign up|registr/i }).click();
    await expect(page.locator("#confirm-password")).toBeVisible();
    await expect(
      page.getByRole("button", { name: /crear cuenta|sign up|registr/i })
    ).toBeVisible();
  });

  test("contraseñas distintas dan error sin navegar", async ({ page }) => {
    await page.getByRole("tab", { name: /crear cuenta|sign up|registr/i }).click();

    await page.locator("#email").fill("nuevo@example.com");
    await page.locator("#password").fill("Abcd123456");
    await page.locator("#confirm-password").fill("Zzzz999999");
    await page.getByRole("button", { name: /crear cuenta|sign up|registr/i }).click();

    // La validación de cliente corre antes de cualquier petición. Se apunta a
    // aria-live="polite" para no capturar el anunciador de rutas de Next.
    await expect(page.locator("[role='alert'][aria-live='polite']")).toContainText(
      /no coinciden|do not match/i
    );
    await expect(page).toHaveURL(/\/login/);
  });
});
