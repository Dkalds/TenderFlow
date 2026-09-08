import { test, expect, type BrowserContext, type Locator, type Page } from "@playwright/test";
import { SEED_LICITACION } from "./fixtures";

/** Mutaciones críticas con persistencia real en Postgres. */
test.describe("Flujos de trabajo críticos", () => {
  test.describe.configure({ mode: "serial" });

  test("guardar una vista sobrevive a la recarga", async ({ page, context }) => {
    const name = "E2E · vista persistente";
    await deleteSavedView(page, context, name);

    try {
      await page.goto("/resumen?tecnologia=SAP");
      await page.getByRole("button", { name: "Vistas" }).click();
      await page.getByRole("textbox", { name: "Nombre de la vista" }).fill(name);
      await page.getByRole("button", { name: "Guardar vista actual" }).click();

      await expect.poll(() => savedViewExists(page, name)).toBe(true);
      await page.reload();
      await page.getByRole("button", { name: "Vistas" }).click();
      // `.first()`: el nombre de la vista aparece en DOS botones (aplicar la
      // vista y «Eliminar <nombre>», cuyo accessible name lo contiene), y el
      // strict mode de Playwright rechaza el locator ambiguo.
      await expect(page.getByRole("button", { name }).first()).toBeVisible();
    } finally {
      await deleteSavedView(page, context, name);
    }
  });

  test("seguir una licitación persiste y se puede deshacer", async ({ page, context }) => {
    // Estuvo en `fixme` desde que se escribió, con la sospecha de que la causa
    // era el `nested-interactive` de la fila. No lo era, y por eso al quitar esa
    // regla el test siguió sin pasar: **las acciones de una fila inactiva son
    // `inert`** (`radar-acciones.tsx`, `inerte = enTabla && !isActive`), y a
    // partir de `md` además llevan `pointer-events-none`. `inert` las saca del
    // árbol de accesibilidad, así que `getByRole("button", {name: /^Seguir /})`
    // no resolvía a nada y `click()` esperaba —sin error— hasta agotar el
    // presupuesto del test. El log de la API del job lo confirma: los `GET
    // /watchlist/items` responden 200 en 30 ms y **no hay ni un POST**.
    //
    // No es un fallo de la aplicación: revelar las acciones solo en la fila
    // activa es una decisión del componente, escrita en su propio docstring. Lo
    // que faltaba era que el test hiciera lo que hace una persona —seleccionar
    // la fila y después pulsar—, y eso es justo lo que el botón en capa de C7.1
    // hace posible expresar.
    //
    // El presupuesto es explícito porque el de por defecto no le cabe: el
    // cuerpo declara **dos** esperas de 20 s —el Radar con datos reales tarda,
    // y por eso las escribió así quien lo escribió— y los 30 s de Playwright
    // no cubren ni esas dos solas, sin contar `goto`, `reload` y los sondeos.
    // Al agotarse, el `finally` heredaba un reloj ya vencido y el fallo se
    // reportaba en la limpieza, no en la aserción: por eso parecía otra cosa.
    // Con el modo `serial` del bloque, además, arrastraba sin ejecutar a los
    // dos tests siguientes.
    test.setTimeout(90_000);
    await removeWatchlistItem(page, context, SEED_LICITACION.radarId);

    try {
      await page.goto("/radar");
      const fila = await seleccionarFila(page, SEED_LICITACION.tituloRadar);
      await fila.getByRole("button", { name: /^Seguir / }).click();

      await expect.poll(() => watchlistContains(page, SEED_LICITACION.radarId)).toBe(true);

      // Se vuelve a seleccionar tras recargar en vez de dar por hecho el estado:
      // «Dejar de seguir» está tan `inert` como lo estaba «Seguir», y si la
      // recarga restaura la selección, volver a pulsar no cambia nada.
      await page.reload();
      const filaTrasRecarga = await seleccionarFila(page, SEED_LICITACION.tituloRadar);
      await filaTrasRecarga.getByRole("button", { name: /^Dejar de seguir / }).click();
      await expect.poll(() => watchlistContains(page, SEED_LICITACION.radarId)).toBe(false);
    } finally {
      await removeWatchlistItem(page, context, SEED_LICITACION.radarId);
    }
  });

  test("exportar el ámbito descarga un CSV servido por la API", async ({ page }) => {
    // Estuvo en `fixme` con el diagnóstico «el evento download no llega en CI».
    // Eso era el síntoma; la causa estaba en `lib/export.ts::volcarBlob`, que
    // revocaba el object URL en la **misma vuelta del event loop** que el
    // `click()` del ancla. El navegador arranca la descarga de forma asíncrona:
    // en un portátil rápido casi siempre ganaba la descarga, en el Chromium
    // headless de CI casi siempre perdía y el fichero no llegaba nunca. La
    // revocación pasa al siguiente tick (2026-09-08, C7.1).
    await page.goto("/resumen?tecnologia=SAP");
    await page.getByRole("button", { name: "Exportar ámbito" }).click();

    const [response, download] = await Promise.all([
      page.waitForResponse(
        (candidate) =>
          candidate.url().includes("/api/v1/exports/download") &&
          candidate.url().includes("format=csv"),
      ),
      page.waitForEvent("download"),
      page.getByRole("menuitem", { name: "Exportar CSV" }).click(),
    ]);

    expect(response.ok()).toBe(true);
    expect(await download.suggestedFilename()).toMatch(/\.csv$/);
  });

  test("el borrado RGPD de la cuenta se ejecuta contra la API real", async ({ browser }) => {
    // Regresión O0.7. El botón hacía `fetch("/api/v1/me", {method:"DELETE"})` a
    // pelo: sin `X-CSRF-Token` (que `require_any_auth` exige a toda mutación
    // por cookie) y sin el cuerpo `{"confirmation":"DELETE"}` que declara
    // `DeleteMyDataRequest`. Devolvía 403 y la pantalla decía «Cuenta
    // eliminada» igualmente… porque tampoco miraba el estado. Este caso lo
    // ejercita de punta a punta contra Postgres.
    //
    // Cuenta desechable, nunca la del seed: el borrado anonimiza el usuario y
    // revoca sus sesiones, así que hacerlo sobre `demo@tenderflow.dev` dejaría
    // sin autenticación al resto de la suite.
    //
    // El alta self-service la abre `ALLOW_SELF_REGISTRATION`, declarada en el
    // job `frontend-e2e` de `ci.yml`. La primera versión de este test daba por
    // hecho que bastaba `ENV=dev` y fallaba con un mensaje que culpaba al sitio
    // equivocado; `web/e2e/login.spec.ts` ya documentaba que en producción la
    // bandera está apagada y `register` responde 403.
    const sello = Date.now();
    // `@example.com` y no `@tenderflow.test`: `email-validator` —el que hay
    // detrás de `EmailStr`— rechaza los TLD de uso especial, así que `.test`
    // devolvía 422 («value is not a valid email address»). Es el mismo dominio
    // que usa `tests/test_auth_register.py`, que sí pasa. El sello temporal
    // mantiene la cuenta única entre ejecuciones.
    const email = `e2e-borrado-${sello}@example.com`;
    // Credencial de una cuenta desechable que este mismo test crea y borra.
    //
    // Se GENERA en ejecución en vez de ir literal: una constante con pinta de
    // contraseña en el repositorio la marca `gitleaks`, y silenciarla con una
    // excepción en `.gitleaks.toml` gastaría una regla de seguridad real en un
    // caso que no la necesita. De paso, cada ejecución usa una distinta.
    //
    // Los 16+ caracteres son obligatorios: `shared/password_policy.py` los
    // exige (`min_length=16`) y `register` responde 400 por debajo de ahí. La
    // primera versión de este test usaba una de 15 y fallaba con el mensaje de
    // «el alta debe estar abierta», que apuntaba al sitio equivocado — el alta
    // SÍ estaba abierta (`ENV=dev`); lo que no cumplía era la contraseña.
    const password = `E2E-${sello}-${Math.random().toString(36).slice(2, 10)}-Ok`; // pragma: allowlist secret

    // Contexto propio: sin `storageState`, para no heredar la sesión demo.
    const context = await browser.newContext();
    try {
      const alta = await context.request.post("/api/v1/auth/register", {
        data: { email, password, display_name: "Cuenta de borrado E2E" },
      });
      // El mensaje lleva el estado Y el cuerpo a propósito. La versión anterior
      // afirmaba «el alta debe estar abierta» pasara lo que pasara, así que un
      // 400 de política de contraseña y un 403 de bandera apagada se leían
      // idénticos y mandaban a mirar el sitio equivocado. Un assert que siempre
      // acusa a la misma causa es peor que uno sin mensaje.
      expect(
        alta.status(),
        `POST /auth/register devolvió ${alta.status()}: ${(await alta.text()).slice(0, 300)}`,
      ).toBe(201);

      const page = await context.newPage();
      await page.goto("/mi-cuenta");
      await page.getByLabel(/para confirmar/).fill(email);

      const [respuesta] = await Promise.all([
        page.waitForResponse(
          (candidate) =>
            candidate.url().endsWith("/api/v1/me") && candidate.request().method() === "DELETE",
        ),
        page.getByRole("button", { name: "Eliminar mi cuenta definitivamente" }).click(),
      ]);

      // El cuerpo se lee con red: tras un borrado con éxito la app navega a
      // `/login` —la sesión acaba de revocarse— y Chromium libera el cuerpo de
      // la respuesta, de modo que `.text()` lanza «Protocol error
      // (Network.getResponseBody): No resource with given identifier found».
      // El estado sigue disponible siempre; el cuerpo solo hace falta para
      // explicar un fallo, así que su ausencia no puede ser el fallo.
      const cuerpo = await respuesta
        .text()
        .catch(() => "<cuerpo no disponible: la página ya había navegado>");

      expect(respuesta.status(), `DELETE /me devolvió ${respuesta.status()}: ${cuerpo}`).toBe(200);
      expect(respuesta.request().headers()["x-csrf-token"]).toBeTruthy();
      expect(JSON.parse(respuesta.request().postData() ?? "{}")).toEqual({
        confirmation: "DELETE",
      });

      // El borrado revoca sesiones y anonimiza la cuenta: volver a entrar falla.
      const reintento = await context.request.post("/api/v1/auth/login", {
        data: { email, password },
      });
      expect(reintento.ok()).toBe(false);
    } finally {
      await context.close();
    }
  });
});

async function csrfHeaders(context: BrowserContext): Promise<Record<string, string>> {
  const token = (await context.cookies()).find((cookie) => cookie.name === "csrf_token")?.value;
  if (!token) throw new Error("La sesión E2E no tiene csrf_token");
  return { "X-CSRF-Token": token };
}

async function savedViewExists(page: Page, name: string): Promise<boolean> {
  const response = await page.request.get("/api/v1/saved-filters");
  if (!response.ok()) return false;
  const body = (await response.json()) as { items: { name: string }[] };
  return body.items.some((view) => view.name === name);
}

async function deleteSavedView(page: Page, context: BrowserContext, name: string): Promise<void> {
  const response = await page.request.get("/api/v1/saved-filters");
  if (!response.ok()) return;
  const body = (await response.json()) as { items: { id: number; name: string }[] };
  const headers = await csrfHeaders(context);
  for (const view of body.items.filter((candidate) => candidate.name === name)) {
    await page.request.delete(`/api/v1/saved-filters/${view.id}`, { headers });
  }
}

/**
 * Deja seleccionada la fila del Radar cuyo título es *titulo* y la devuelve.
 *
 * Hace falta porque las acciones de una fila inactiva son `inert` y, en la
 * tabla, `pointer-events-none`: sin seleccionarla primero, «Seguir» no está en
 * el árbol de accesibilidad y el locator no resuelve nunca. Seleccionar es el
 * botón en capa que introdujo C7.1 (`aria-label="Seleccionar …"`).
 */
async function seleccionarFila(page: Page, titulo: string): Promise<Locator> {
  // El ancla es el botón en capa y no el texto del título: al seleccionar una
  // fila se abre el inspector, que **repite** ese título en el panel lateral.
  // Un `getByText(titulo).first()` acertaba con la lista vacía de selección y
  // pasaba a resolver al panel en cuanto había una fila activa —tras el
  // `reload()`, que restaura la selección—, y el ancestro del panel no tiene
  // `data-active`: el locator no resolvía a nada y `click()` esperaba en
  // silencio. `aria-label="Seleccionar …"` solo existe en las filas del Radar.
  const seleccion = page.getByRole("button", { name: `Seleccionar ${titulo}` });
  await expect(seleccion).toBeVisible({ timeout: 20_000 });
  await seleccion.click();
  const fila = seleccion.locator("xpath=ancestor::*[@data-active][1]");
  await expect(fila).toHaveAttribute("data-active", "true");
  return fila;
}

async function watchlistContains(page: Page, idExterno: string): Promise<boolean> {
  const response = await page.request.get("/api/v1/watchlist/items");
  if (!response.ok()) return false;
  const body = (await response.json()) as { items: { id_externo: string }[] };
  return body.items.some((item) => item.id_externo === idExterno);
}

async function removeWatchlistItem(
  page: Page,
  context: BrowserContext,
  idExterno: string,
): Promise<void> {
  if (!(await watchlistContains(page, idExterno))) return;
  await page.request.delete(`/api/v1/watchlist/items/${encodeURIComponent(idExterno)}`, {
    headers: await csrfHeaders(context),
  });
}
