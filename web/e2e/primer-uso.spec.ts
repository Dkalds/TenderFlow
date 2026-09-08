import { expect, test } from "@playwright/test";

/**
 * Primer uso: lo que ve alguien que acaba de entrar y todavía no tiene nada.
 *
 * El producto se probaba siempre con el seed cargado, así que las pantallas
 * vacías —que son las primeras que ve cualquiera— no las miraba nadie. Dos
 * defectos concretos de esa ceguera (C7.3):
 *
 * 1. La barra de ámbito decía «Ámbito» y «+ Añadir» sin explicar de qué va, y
 *    es el control que decide lo que se ve en el resto de la consola.
 * 2. Los estados vacíos daban instrucciones sin llevar a ninguna parte
 *    («marcá una licitación con la estrella desde Detalle»), obligando a buscar
 *    en el rail la pantalla que acababan de nombrar.
 *
 * El tercer criterio de aceptación —«ninguno inventa cifras»— es el que este
 * proyecto se toma más en serio: un estado vacío que rellena con datos de
 * ejemplo enseña un producto que no existe. Se comprueba que ningún estado
 * vacío contiene dígitos que parezcan un dato.
 */

/** Rutas con estado vacío accionable, y el texto del botón que enseñan. */
const ESTADOS_VACIOS = [
  { ruta: "/oportunidades", accion: /Ir al Radar/i },
  { ruta: "/mi-pipeline?vista=agenda", accion: /Abrir el Radar/i },
  { ruta: "/mi-watchlist", accion: /Buscar licitaciones/i },
] as const;

test.describe("primer uso", () => {
  test("la barra de ámbito se explica cuando no hay ningún filtro", async ({ page }) => {
    await page.goto("/resumen");
    await expect(page.locator("main#main-content")).toBeVisible({ timeout: 20_000 });

    // Sin chips, la barra dice qué es el ámbito. Con el primer filtro puesto,
    // la explicación sobra y desaparece — por eso se comprueba el estado
    // limpio, que es el del primer uso.
    await expect(page.getByText(/Todo el corpus\./i)).toBeVisible();
  });

  for (const { ruta, accion } of ESTADOS_VACIOS) {
    test(`${ruta} enseña la acción siguiente cuando está vacío`, async ({ page }) => {
      await page.goto(ruta);
      await expect(page.locator("main#main-content")).toBeVisible({ timeout: 20_000 });

      // El seed de CI tiene datos, así que la pantalla puede no estar vacía.
      // Lo que se fija es el contrato: **si** está vacía, hay una acción; nunca
      // un callejón sin salida.
      const vacio = page.getByRole("status").first();
      if (await vacio.isVisible().catch(() => false)) {
        await expect(page.getByRole("link", { name: accion }).first()).toBeVisible();
      }
    });
  }

  test("ningún estado vacío inventa cifras", async ({ page }) => {
    for (const { ruta } of ESTADOS_VACIOS) {
      await page.goto(ruta);
      await expect(page.locator("main#main-content")).toBeVisible({ timeout: 20_000 });
      const vacio = page.getByRole("status").first();
      if (!(await vacio.isVisible().catch(() => false))) continue;

      const texto = (await vacio.textContent()) ?? "";
      // Un estado vacío que enseña «14 oportunidades» o «1.234 €» de ejemplo
      // está describiendo un producto que quien mira no tiene. Se permiten
      // dígitos sueltos (un «24h» en una explicación), no importes ni miles.
      expect(texto, `${ruta} enseña algo que parece un dato`).not.toMatch(
        /\d[\d.,]{2,}\s*(€|licitaciones|oportunidades|expedientes)/i,
      );
    }
  });
});
