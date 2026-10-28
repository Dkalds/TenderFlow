import { PRESUPUESTO_RECORRIDO_MS, test, expect } from "./cuenta-desechable";
import { SEED_LICITACION } from "./fixtures";
import { seleccionarFilaDelRadar } from "./radar-fila";

/**
 * Los primeros pasos de una cuenta recién creada, del Resumen a donde se hace
 * cada uno (B5 del plan 2026-10).
 *
 * Con cuenta desechable: una cuenta nueva es justo la que ve la banda, y abrir
 * una oportunidad le cambia el tablero y la Agenda a quien la abre.
 *
 * No se asume nada de la alerta: con D53 una organización puede nacer ya con
 * la suya, y el recorrido no depende de cuál de los dos estados encuentre.
 */

const CAPACIDAD = "Completa la capacidad de tu organización";
const ALERTA = "Revisa tu alerta";
const OPORTUNIDAD = "Abre tu primera oportunidad";

test("los primeros pasos llevan a la capacidad, la alerta y la primera oportunidad, y se marcan solos", async ({
  page,
}) => {
  // CU-34
  test.setTimeout(PRESUPUESTO_RECORRIDO_MS);

  // ── Una cuenta nueva ve los pasos y adónde lleva cada uno ────────────────
  await page.goto("/resumen");
  await expect(page.getByRole("heading", { name: "Primeros pasos" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("link", { name: new RegExp(CAPACIDAD) })).toHaveAttribute(
    "href",
    "/equipo?tab=organizacion",
  );
  await expect(page.getByRole("link", { name: new RegExp(OPORTUNIDAD) })).toHaveAttribute("href", "/radar");
  // La alerta, pendiente o ya revisada: la fila está, diga lo que diga.
  await expect(page.locator("li").filter({ hasText: ALERTA })).toBeVisible();

  // ── La capacidad se completa en Equipo › Organización ────────────────────
  await page.getByRole("link", { name: new RegExp(CAPACIDAD) }).click();
  await page.waitForURL((url) => url.pathname === "/equipo" && url.searchParams.get("tab") === "organizacion");
  await expect(page.getByRole("tab", { name: "Organización" })).toHaveAttribute("aria-selected", "true");

  // ── Abrir una oportunidad marca su paso ──────────────────────────────────
  await page.goto("/radar");
  const fila = await seleccionarFilaDelRadar(page, SEED_LICITACION.tituloRadar);
  const [alta] = await Promise.all([
    page.waitForResponse(
      (candidata) => /\/api\/v1\/pursuits(\?|$)/.test(candidata.url()) && candidata.request().method() === "POST",
    ),
    fila.getByRole("button", { name: "Abrir", exact: true }).click(),
  ]);
  expect(alta.status(), "POST /pursuits").toBe(201);
  await page.waitForURL(/\/oportunidades\/\d+$/);

  await page.goto("/resumen");
  // La capacidad sigue pendiente, así que la banda sigue; el paso de la
  // oportunidad ya no es un enlace: está hecho.
  const pasoOportunidad = page.locator("li").filter({ hasText: OPORTUNIDAD });
  await expect(pasoOportunidad).toContainText("hecho", { timeout: 20_000 });
  await expect(pasoOportunidad.getByRole("link")).toHaveCount(0);
  await expect(page.locator("li").filter({ hasText: CAPACIDAD })).toContainText("pendiente");
});
