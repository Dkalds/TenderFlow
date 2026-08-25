import { test, expect } from "@playwright/test";
import { SEED_LICITACION } from "./fixtures";

/**
 * Regresión visual de las pantallas principales.
 *
 * Cubre la clase de fallo que ninguna aserción funcional ve: "los primitivos
 * compartidos llevaban la piel anterior". Un botón con el radio equivocado o
 * una tabla que perdió su densidad pasan todos los tests de comportamiento y
 * llegan a producción.
 *
 * Baselines
 * ---------
 * **Todavía no hay baselines commiteados**, y por eso estos tests se saltan
 * salvo que se pidan explícitamente con `VISUAL_BASELINE=1`. Las capturas
 * dependen del renderizado de fuentes del sistema: generarlas en una máquina
 * distinta de la del CI produce diferencias en cada píxel de texto y el gate
 * nace inútil.
 *
 * Para activarlo, una vez, desde un runner de CI (Linux):
 *
 *     VISUAL_BASELINE=1 npx playwright test visual --project=chromium --update-snapshots
 *
 * commitear `visual.spec.ts-snapshots/` y quitar el `skip` de abajo. A partir
 * de ahí, cada cambio de diseño intencionado regenera los baselines en el
 * mismo PR, revisando las imágenes una a una: un baseline actualizado sin
 * mirar no protege de nada.
 *
 * Solo chromium: mantener tres juegos de baselines triplica el mantenimiento
 * sin triplicar la señal.
 */

const PANTALLAS = [
  { nombre: "resumen", ruta: "/resumen" },
  { nombre: "radar", ruta: "/radar" },
  { nombre: "detalle", ruta: `/detalle?lic=${SEED_LICITACION.id}` },
  { nombre: "mercado", ruta: "/mercado" },
  { nombre: "competencia", ruta: "/competencia" },
  { nombre: "oportunidades", ruta: "/oportunidades" },
];

test.describe("Regresión visual", () => {
  test.skip(
    ({ browserName }) => browserName !== "chromium",
    "Los baselines se mantienen solo para chromium"
  );
  test.skip(
    !process.env.VISUAL_BASELINE,
    "Sin baselines commiteados todavía: ver la cabecera de este fichero"
  );

  for (const { nombre, ruta } of PANTALLAS) {
    test(`${nombre} coincide con su baseline`, async ({ page }) => {
      await page.goto(ruta);
      await expect(page.locator("main").first()).toBeVisible({ timeout: 20000 });
      // Las animaciones de entrada deben haber terminado antes de comparar.
      await page.waitForLoadState("networkidle");

      await expect(page).toHaveScreenshot(`${nombre}.png`, {
        fullPage: true,
        // Tolerancia para el antialiasing de texto entre ejecuciones.
        maxDiffPixelRatio: 0.02,
        // La barra de ámbito muestra "sync hace N minutos": cambia en cada
        // ejecución y haría fallar la comparación por un dato que no es diseño.
        mask: [page.getByText(/sync hace/i)],
        animations: "disabled",
      });
    });
  }
});

/**
 * La portada, aparte y sin sesión.
 *
 * Va en su propio bloque por un motivo que no es de estilo: con la sesión del
 * proyecto, `/` redirige al dashboard, así que añadirla a `PANTALLAS` habría
 * capturado la consola creyendo capturar la landing — un baseline verde sobre
 * la página equivocada.
 *
 * Y merece estar: es la única pantalla del producto cuyo daño por regresión
 * visual es directo, porque es la primera —y a veces la única— que ve alguien
 * que todavía no es usuario.
 */
test.describe("Regresión visual de la portada", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test.skip(
    ({ browserName }) => browserName !== "chromium",
    "Los baselines se mantienen solo para chromium"
  );
  test.skip(
    !process.env.VISUAL_BASELINE,
    "Sin baselines commiteados todavía: ver la cabecera de este fichero"
  );

  test("la portada coincide con su baseline", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("main").first()).toBeVisible({ timeout: 20000 });
    await page.waitForLoadState("networkidle");

    await expect(page).toHaveScreenshot("portada.png", {
      fullPage: true,
      maxDiffPixelRatio: 0.02,
      // La franja de cifras trae tres números del corpus y la fecha del último
      // expediente: cambian con la ingesta y no son diseño. Enmascararlos es lo
      // que hace que este baseline dure más de un día.
      mask: [page.getByLabel("El corpus en cifras")],
      animations: "disabled",
    });
  });
});
