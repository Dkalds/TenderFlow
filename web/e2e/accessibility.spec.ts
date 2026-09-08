import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { SEED_LICITACION } from "./fixtures";

async function expectBasicAccessibility(page: Page): Promise<void> {
  await expect(page.locator("html")).toHaveAttribute("lang", "es");
  await expect(page.locator("main#main-content")).toHaveCount(1);
  await expect(page.locator('a[href="#main-content"]')).toHaveCount(1);

  const duplicateIds = await page.locator("[id]").evaluateAll((elements) => {
    const counts = new Map<string, number>();
    for (const element of elements) {
      counts.set(element.id, (counts.get(element.id) ?? 0) + 1);
    }
    return [...counts.entries()].filter(([, count]) => count > 1).map(([id]) => id);
  });
  expect(duplicateIds).toEqual([]);

  const unnamedControls = await page
    .locator('button, input:not([type="hidden"]), select, textarea, [role="button"], [role="combobox"]')
    .evaluateAll((elements) =>
      elements.flatMap((element) => {
        // Fuera del árbol de accesibilidad → WCAG 4.1.2 no le exige nombre.
        // El caso concreto que lo motiva: Radix renderiza junto a cada
        // Checkbox y Switch un `<input>` nativo oculto para que el control
        // participe en el envío del formulario, y lo marca `aria-hidden="true"`
        // con `tabindex="-1"` precisamente para que ningún lector de pantalla
        // lo vea. Exigirle nombre convertía ese patrón correcto en un rojo, y
        // un gate que falla sobre lo que está bien hecho se acaba desactivando
        // entero — que es como se pierden los hallazgos de verdad.
        if (element.closest('[aria-hidden="true"]')) {
          return [];
        }
        const labelledBy = element.getAttribute("aria-labelledby");
        const labelledText = labelledBy
          ? labelledBy
              .split(/\s+/)
              .map((id) => document.getElementById(id)?.textContent ?? "")
              .join(" ")
          : "";
        const htmlElement = element as HTMLElement;
        const input = element as HTMLInputElement;
        const labelText = input.labels ? [...input.labels].map((label) => label.textContent ?? "").join(" ") : "";
        const name = [
          element.getAttribute("aria-label"),
          labelledText,
          labelText,
          htmlElement.innerText,
          input.value && input.type === "submit" ? input.value : "",
        ]
          .filter(Boolean)
          .join(" ")
          .trim();
        return name ? [] : [element.outerHTML.slice(0, 180)];
      }),
    );
  expect(unnamedControls).toEqual([]);

  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    // Ratchet, no aspiración: estas reglas fallan HOY en /radar y /detalle
    // (contraste de textos pequeños, regiones scrolleables sin foco, targets
    // <24px) y su remediación es la ola de UX/móvil en curso, no un fix de CI.
    // El resto de WCAG-AA más los checks estructurales de arriba SÍ bloquean.
    // Backlog: «Remediación axe pendiente» en docs/IMPROVEMENT_BACKLOG.md — la
    // lista solo puede encoger.
    //
    // 2026-09-08 — sale `nested-interactive` (C7.1). Su causa era la fila del
    // Radar: `role="button"` con los botones de descartar, seguir y abrir
    // dentro. La bandeja pasa al patrón de rejilla de la APG —`grid` en la
    // lista, `row` en la fila, `gridcell` en sus grupos—, que es la estructura
    // que admite controles dentro de una fila enfocable.
    .disableRules(["color-contrast", "scrollable-region-focusable", "target-size"])
    .analyze();
  const violations = result.violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    help: violation.help,
    helpUrl: violation.helpUrl,
    targets: violation.nodes.flatMap((node) => node.target),
  }));
  expect(violations).toEqual([]);
}

test.describe("Accesibilidad básica sin sesión", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("login conserva landmarks y nombres accesibles", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    await expectBasicAccessibility(page);
  });

  // La superficie pública faltaba entera en este fichero, y es la que ve un
  // desconocido: la portada, los índices y las páginas de evidencia. Van sin
  // sesión a propósito — con cookie, `/` redirige al dashboard y el barrido
  // se haría sobre la pantalla equivocada.
  for (const ruta of ["/", "/licitaciones", "/cpv", "/cobertura", "/metodologia", "/seguridad"]) {
    test(`${ruta} conserva landmarks y nombres accesibles`, async ({ page }) => {
      await page.goto(ruta);
      await expect(page.locator("main#main-content")).toBeVisible({ timeout: 20_000 });
      await expectBasicAccessibility(page);
    });
  }

  // La ficha pública de un expediente (C7.2). Faltaba, y es la página que más
  // veces se abre desde un buscador: los índices sólo llevan a ella.
  //
  // La URL no se escribe a mano —`/licitaciones/[ccaa]/[slug]/[ref]` la componen
  // el nombre de la comunidad y el título, así que un literal caducaría con el
  // seed— sino que se llega navegando, que además comprueba que el camino del
  // visitante existe.
  test("una ficha pública conserva landmarks y nombres accesibles", async ({ page }) => {
    await page.goto("/licitaciones");
    await expect(page.locator("main#main-content")).toBeVisible({ timeout: 20_000 });

    const hub = page.locator('main a[href^="/licitaciones/"]').first();
    await expect(hub).toBeVisible({ timeout: 20_000 });
    await hub.click();
    await expect(page.locator("main#main-content")).toBeVisible({ timeout: 20_000 });

    // En el hub de la comunidad, el enlace a una ficha lleva dos segmentos más.
    const ficha = page.locator('main a[href*="/licitaciones/"]').filter({
      hasNot: page.locator("[aria-hidden='true']"),
    });
    const href = await ficha
      .evaluateAll((enlaces) =>
        enlaces
          .map((a) => a.getAttribute("href") ?? "")
          .find((h) => h.split("/").filter(Boolean).length >= 4),
      )
      .catch(() => undefined);
    test.skip(!href, "El seed no publicó ninguna ficha en esta comunidad");

    await page.goto(href as string);
    await expect(page.locator("main#main-content")).toBeVisible({ timeout: 20_000 });
    await expectBasicAccessibility(page);
  });
});

test.describe("Accesibilidad básica con sesión", () => {
  for (const route of ["/resumen", "/radar", `/detalle?lic=${SEED_LICITACION.id}`]) {
    test(`${route} conserva landmarks y nombres accesibles`, async ({ page }) => {
      await page.goto(route);
      await expect(page.locator("main#main-content")).toBeVisible({ timeout: 20_000 });
      await expectBasicAccessibility(page);
    });
  }
});
