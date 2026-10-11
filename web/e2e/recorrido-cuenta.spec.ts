import type { Locator, Page } from "@playwright/test";
import { PRESUPUESTO_RECORRIDO_MS, test, expect } from "./cuenta-desechable";
import { SEED_LICITACION } from "./fixtures";

/**
 * Una cuenta objetivo, del buscador de órganos a dejar de seguirla.
 *
 * Con cuenta desechable: las cuentas son de la organización, y un órgano solo
 * puede ser de una. Con el usuario del seed, un test que se quedara a medias
 * dejaría «Ministerio de Hacienda» cogido para todos los que vinieran detrás.
 */

const ORGANO = SEED_LICITACION.organo;
const NOTA = "Renueva el parque de equipos cada cuatro años.";

test("un órgano del seed se convierte en cuenta, se abre su ficha y vuelve a quedar libre", async ({ page }) => {
  // CU-11
  test.setTimeout(PRESUPUESTO_RECORRIDO_MS);
  await page.goto("/cuentas");
  await expect(page.getByText("Tu equipo todavía no sigue ninguna cuenta")).toBeVisible();

  // ── Buscar el órgano y crear la cuenta ───────────────────────────────────
  const dialogo = await abrirAlta(page);
  const opcion = await buscarOrgano(dialogo);
  // Recién creada la organización, el órgano no es de nadie.
  await expect(opcion).not.toHaveAttribute("aria-disabled", "true");
  await opcion.click();
  await expect(dialogo.getByRole("list", { name: "Órganos elegidos" })).toContainText(ORGANO);
  await dialogo.getByLabel("Nota").fill(NOTA);

  const [alta] = await Promise.all([
    page.waitForResponse(
      (candidata) => /\/api\/v1\/cuentas(\?|$)/.test(candidata.url()) && candidata.request().method() === "POST",
    ),
    dialogo.getByRole("button", { name: "Crear cuenta" }).click(),
  ]);
  expect(alta.status(), "POST /cuentas").toBe(201);
  await expect(dialogo).toBeHidden();

  // Sin nombre propio, la cuenta se llama como su órgano.
  const enlace = page.getByRole("link", { name: ORGANO, exact: true });
  await expect(enlace).toBeVisible();

  // ── Su ficha ─────────────────────────────────────────────────────────────
  await enlace.click();
  await page.waitForURL(/\/cuentas\/\d+$/);
  await expect(page.getByRole("heading", { level: 1, name: ORGANO })).toBeVisible();
  await expect(page.getByText(NOTA)).toBeVisible();
  // Los bloques de la ficha, y el órgano que la compone con su salida a
  // Mercado. No se afirma qué publicaciones lista: esa ventana va por
  // `primera_extraccion`, que la ingesta rellena y `seed_dev.py` deja vacía,
  // así que con datos sembrados el bloque dice —con razón— que no hay nada.
  await expect(page.getByRole("heading", { name: "Publicaciones recientes" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Contratos que vencen" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Oportunidades del equipo" })).toBeVisible();
  // Dentro de `main`: la franja que explica el ámbito a quien entra por
  // primera vez también es un `complementary`, y donde sale va fuera de él.
  const organos = page.getByRole("main").getByRole("complementary").getByRole("listitem");
  await expect(organos).toHaveCount(1);
  await expect(organos.getByRole("link", { name: ORGANO })).toHaveAttribute(
    "href",
    /^\/mercado\?vista=organos&organo_q=/,
  );

  // La ficha es una URL, no un estado de la lista: aguanta una recarga.
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: ORGANO })).toBeVisible();

  // ── Dejar de seguirla ────────────────────────────────────────────────────
  const [baja] = await Promise.all([
    page.waitForResponse(
      (candidata) => /\/api\/v1\/cuentas\/\d+/.test(candidata.url()) && candidata.request().method() === "DELETE",
    ),
    page.getByRole("button", { name: "Dejar de seguir" }).click(),
  ]);
  expect(baja.ok(), `DELETE de la cuenta devolvió ${baja.status()}`).toBe(true);

  await page.waitForURL(/\/cuentas$/);
  await expect(page.getByText("Tu equipo todavía no sigue ninguna cuenta")).toBeVisible();

  // El órgano vuelve a estar libre: el buscador ya no dice que es de una
  // cuenta. Tras recargar, para que la respuesta sea del servidor de ahora y
  // no la que la pantalla guardó de la primera búsqueda, cuando aún no lo era.
  await page.reload();
  const otraVez = await abrirAlta(page);
  const libre = await buscarOrgano(otraVez);
  await expect(libre).not.toHaveAttribute("aria-disabled", "true");
  await expect(libre).not.toContainText("ya está en la cuenta");
});

async function abrirAlta(page: Page): Promise<Locator> {
  // `.first()`: con la lista vacía hay dos «Nueva cuenta», el de la cabecera
  // y el del estado vacío, y abren el mismo diálogo.
  await page.getByRole("button", { name: "Nueva cuenta" }).first().click();
  const dialogo = page.getByRole("dialog", { name: "Nueva cuenta" });
  await expect(dialogo).toBeVisible();
  return dialogo;
}

/** Teclea el órgano en el buscador del alta y devuelve su opción de la lista. */
async function buscarOrgano(dialogo: Locator): Promise<Locator> {
  await dialogo.getByRole("combobox", { name: "Órganos de contratación" }).fill(ORGANO);
  // El nombre de la opción sigue con «N expedientes», que no es parte del
  // órgano: se ancla solo el principio.
  const opcion = dialogo
    .getByRole("listbox", { name: "Órganos que coinciden" })
    .getByRole("option", { name: new RegExp(`^${ORGANO}`) });
  await expect(opcion).toBeVisible();
  return opcion;
}
