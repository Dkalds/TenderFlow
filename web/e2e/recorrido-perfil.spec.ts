import type { Page } from "@playwright/test";
import { PRESUPUESTO_RECORRIDO_MS, test, expect } from "./cuenta-desechable";

/**
 * El perfil de puntuación: cambiarlo, guardarlo con la barra y borrarlo.
 *
 * Con cuenta desechable: el perfil decide el orden y la puntuación del Radar
 * de quien lo guarda, y varios specs buscan en el Radar del usuario del seed
 * una fila concreta con los pesos por defecto.
 */

const PALABRA = "municipal";
/** El peso de «Importe» sin perfil propio, y lo que el test le suma. */
const IMPORTE_POR_DEFECTO = 20;
const PASOS = 5;

test("el perfil guarda una palabra clave y un peso, los conserva al recargar y vuelve al defecto al borrarlo", async ({
  page,
}) => {
  // CU-17
  test.setTimeout(PRESUPUESTO_RECORRIDO_MS);
  await page.goto("/mi-perfil");
  const guardar = page.getByRole("button", { name: "Guardar perfil" });
  const importe = page.getByRole("slider", { name: "Peso de Importe" });
  const chip = page.getByRole("button", { name: `Quitar ${PALABRA}` });

  // Una cuenta nueva no tiene perfil: ve los pesos globales y nada que guardar.
  await expect(importe).toHaveAttribute("aria-valuenow", String(IMPORTE_POR_DEFECTO));
  await expect(guardar).toBeDisabled();

  // ── Cambiar una palabra clave y un peso ──────────────────────────────────
  const nuevaPalabra = page.getByRole("textbox", { name: "Nueva palabra clave de afinidad" });
  await nuevaPalabra.fill(PALABRA);
  // Con ⏎, que es el gesto del campo: la pantalla tiene dos «Añadir» iguales,
  // el de las palabras clave y el de los CPV.
  await nuevaPalabra.press("Enter");
  await expect(chip).toBeVisible();

  // Con el teclado y no arrastrando: cada flecha es un punto exacto, y un
  // arrastre depende de cuántos píxeles mida el deslizador en cada máquina.
  await importe.focus();
  for (let paso = 0; paso < PASOS; paso += 1) await importe.press("ArrowRight");
  const importeNuevo = String(IMPORTE_POR_DEFECTO + PASOS);
  await expect(importe).toHaveAttribute("aria-valuenow", importeNuevo);

  // ── Guardar con la barra ─────────────────────────────────────────────────
  await expect(page.getByRole("status").filter({ hasText: "Cambios sin guardar" })).toBeVisible();
  const [guardado] = await Promise.all([escrituraDelPerfil(page, "PUT"), guardar.click()]);
  expect(guardado.status(), "PUT /me/profile").toBe(200);
  const cuerpo = JSON.parse(guardado.request().postData() ?? "{}") as {
    weights: Record<string, number>;
    afinidad_keywords: string[];
  };
  expect(cuerpo.afinidad_keywords).toEqual([PALABRA]);
  // El reparto se hace solo: lo que sube «Importe» lo ceden los demás, y lo
  // que se guarda sigue sumando 100 (la penalización va aparte).
  const { organo_anula_frecuente: _penalizacion, ...dimensiones } = cuerpo.weights;
  expect(Object.values(dimensiones).reduce((suma, peso) => suma + peso, 0)).toBe(100);

  await expect(page.getByText("Sin cambios que guardar.")).toBeVisible();
  await expect(guardar).toBeDisabled();

  // ── Sigue ahí al recargar ────────────────────────────────────────────────
  await page.reload();
  await expect(chip).toBeVisible();
  await expect(importe).toHaveAttribute("aria-valuenow", importeNuevo);
  await expect(guardar).toBeDisabled();

  // ── Borrarlo devuelve los pesos globales ─────────────────────────────────
  await page.getByRole("button", { name: "Eliminar perfil" }).click();
  const confirmacion = page.getByRole("group", { name: "Confirmar eliminación del perfil" });
  const [borrado] = await Promise.all([
    escrituraDelPerfil(page, "DELETE"),
    confirmacion.getByRole("button", { name: "Sí, eliminar" }).click(),
  ]);
  expect(borrado.ok(), `DELETE /me/profile devolvió ${borrado.status()}`).toBe(true);

  await expect(importe).toHaveAttribute("aria-valuenow", String(IMPORTE_POR_DEFECTO));
  await expect(chip).toHaveCount(0);

  await page.reload();
  await expect(importe).toHaveAttribute("aria-valuenow", String(IMPORTE_POR_DEFECTO));
  await expect(chip).toHaveCount(0);
  // Sin perfil propio no hay nada que borrar: el botón no se ofrece.
  await expect(page.getByRole("button", { name: "Eliminar perfil" })).toHaveCount(0);
});

function escrituraDelPerfil(page: Page, metodo: "PUT" | "DELETE") {
  return page.waitForResponse(
    (candidata) => /\/api\/v1\/me\/profile(\?|$)/.test(candidata.url()) && candidata.request().method() === metodo,
  );
}
