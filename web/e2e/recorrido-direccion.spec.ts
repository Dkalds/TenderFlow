import type { Page, Response } from "@playwright/test";
import { PRESUPUESTO_RECORRIDO_MS, test, expect } from "./cuenta-desechable";

/**
 * Dirección: el resultado, la carga por persona y la actividad del equipo.
 *
 * Con cuenta desechable: quien se da de alta es la propietaria de su
 * organización personal, que es justo el rol que ve Dirección. Con el usuario
 * del seed el recorrido dependería de qué oportunidades le dejaron otros specs.
 *
 * No se afirma ninguna cifra: con una organización recién creada no hay
 * cierres, y la pantalla no publica tasas por debajo del mínimo. Lo que se
 * comprueba es que cada vista pide su endpoint, la API contesta 200 y la vista
 * pinta su contenido y no un fallo.
 */

/** La respuesta GET de `ruta` (sin query), contestada mientras se ejecuta `accion`. */
async function conRespuesta(page: Page, ruta: string, accion: () => Promise<unknown>): Promise<Response> {
  const patron = new RegExp(`${ruta.replaceAll("/", "\\/")}(\\?|$)`);
  const [respuesta] = await Promise.all([
    page.waitForResponse((candidata) => patron.test(candidata.url()) && candidata.request().method() === "GET"),
    accion(),
  ]);
  return respuesta;
}

test("la propietaria ve el resultado, la carga por persona y la actividad del equipo", async ({ page, cuenta }) => {
  // CU-24
  test.setTimeout(PRESUPUESTO_RECORRIDO_MS);

  // ── Resultado ────────────────────────────────────────────────────────────
  const cuadro = await conRespuesta(page, "/api/v1/pursuits/direccion", () => page.goto("/direccion"));
  expect(cuadro.status(), "GET /pursuits/direccion").toBe(200);
  await expect(page.getByRole("link", { name: "Embudo completo en Rendimiento" })).toBeVisible();
  await expect(page.getByText("No se ha podido cargar Dirección")).toHaveCount(0);
  await expect(page.getByText("Dirección es solo para propietarios y administradores")).toHaveCount(0);

  // ── Carga del equipo: una fila por persona activa ────────────────────────
  const carga = await conRespuesta(page, "/api/v1/pursuits/direccion/carga", () =>
    page.goto("/direccion?vista=carga"),
  );
  expect(carga.status(), "GET /pursuits/direccion/carga").toBe(200);
  await expect(page.getByRole("heading", { name: "Carga del equipo" })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: cuenta.nombre })).toBeVisible();

  // ── Actividad del equipo ─────────────────────────────────────────────────
  const actividad = await conRespuesta(page, "/api/v1/pursuits/actividad", () =>
    page.goto("/direccion?vista=actividad"),
  );
  expect(actividad.status(), "GET /pursuits/actividad").toBe(200);
  await expect(page.getByText("No se ha podido cargar la actividad")).toHaveCount(0);
  // Sin oportunidades todavía, la vista lo dice en vez de quedarse en blanco.
  await expect(page.getByText("Sin actividad", { exact: true })).toBeVisible();
});
