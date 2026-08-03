import { test, expect } from "@playwright/test";
import { ALL_PAGES } from "../src/lib/navigation";
import { legacyRedirects } from "../src/lib/space-views";
import { SEED_LICITACION } from "./fixtures";

/**
 * Navegación con sesión real contra el backend sembrado.
 *
 * Antes estos tests aceptaban "estoy en el dashboard O en el login" como
 * éxito: sin sesión todas las rutas redirigían a /login, así que el bucle de
 * 26 páginas cargaba 26 veces la misma pantalla de login y pasaba igual con la
 * aplicación entera rota. Y el filtro de errores de consola descartaba
 * "fetch", "500" y "404" porque no había backend — justo las señales que
 * importan. Ahora hay sesión, hay datos, y cada aserción exige una sola
 * respuesta correcta.
 */

const REDIRECTS = legacyRedirects();
const SLUGS_REDIRIGIDOS = new Set(REDIRECTS.map((r) => r.source.replace(/^\//, "")));
const PAGINAS_DE_CONTENIDO = ALL_PAGES.filter((p) => !SLUGS_REDIRIGIDOS.has(p.slug));

/**
 * Ruido que no delata un fallo de la aplicación: violaciones de la CSP en modo
 * Report-Only y los scripts de Vercel Analytics, que solo existen desplegados
 * en Vercel y dan 404 en cualquier otro entorno.
 */
function esRuidoConocido(texto: string): boolean {
  return /Content[- ]Security[- ]Policy|Report Only|favicon|_vercel\/(speed-)?insights/i.test(
    texto
  );
}

test.describe("Sin sesión", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("una ruta protegida redirige a /login", async ({ page }) => {
    await page.goto("/resumen");
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("Con sesión", () => {
  test("la barra de ámbito refleja las licitaciones sembradas", async ({ page }) => {
    await page.goto("/resumen");

    await expect(page).toHaveURL(/\/resumen/);
    await expect(page.locator("nav").first()).toBeVisible();
    // El contador del ámbito sale de contar en backend: si la API no responde
    // o devuelve vacío, aquí habría un 0 y el test cae. Es la aserción que
    // distingue "la página pinta" de "la página pinta datos".
    await expect(page.getByText(/15 licitaciones/)).toBeVisible({ timeout: 20000 });
  });

  test("el radar lista una licitación real del seed", async ({ page }) => {
    await page.goto("/radar");

    await expect(
      page.getByText(SEED_LICITACION.tituloRadar).first()
    ).toBeVisible({ timeout: 20000 });
  });

  // Derivado de `legacyRedirects()`, la misma fuente que consume
  // next.config.ts: si alguien añade o quita un redirect, queda cubierto solo.
  for (const { source, destination } of REDIRECTS) {
    test(`${source} redirige a ${destination}`, async ({ page }) => {
      await page.goto(source);
      const [ruta, query] = destination.split("?");
      await expect(page).toHaveURL(new RegExp(`${ruta.replace(/\//g, "\\/")}.*${query}`));
    });
  }

  for (const pagina of PAGINAS_DE_CONTENIDO) {
    test(`/${pagina.slug} carga sin errores de consola`, async ({ page }) => {
      const errores: string[] = [];
      page.on("console", (msg) => {
        // "Failed to load resource: … 404" no incluye la URL en el texto, así
        // que ese caso se filtra por respuesta (abajo) y no por mensaje.
        const esFalloDeRecurso = /Failed to load resource/i.test(msg.text());
        if (msg.type() === "error" && !esRuidoConocido(msg.text()) && !esFalloDeRecurso) {
          errores.push(msg.text());
        }
      });
      page.on("pageerror", (err) => errores.push(err.message));
      page.on("response", (respuesta) => {
        if (respuesta.status() >= 400 && !esRuidoConocido(respuesta.url())) {
          errores.push(`${respuesta.status()} ${respuesta.url()}`);
        }
      });

      await page.goto(`/${pagina.slug}`);

      // La URL se mantiene: no hubo redirect a login ni a un 404.
      await expect(page).toHaveURL(new RegExp(`/${pagina.slug}`));
      // Se exige contenido en `main`, no un heading concreto: el nivel varía
      // por página (h1 en Resumen, h3 en Radar) y anclar el test a eso lo
      // haría fallar por rediseños que no rompen nada.
      const principal = page.locator("main").first();
      await expect(principal).toBeVisible({ timeout: 20000 });
      await expect(principal).not.toBeEmpty();
      expect(errores, `Errores de consola en /${pagina.slug}`).toEqual([]);
    });
  }
});
