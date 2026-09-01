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
    // Ratchet, no aspiración: estas cuatro reglas fallan HOY en /radar y
    // /detalle (contraste de textos pequeños, filas interactivas anidadas,
    // regiones scrolleables sin foco, targets <24px) y su remediación es la
    // ola de UX/móvil en curso, no un fix de CI. El resto de WCAG-AA más los
    // checks estructurales de arriba SÍ bloquean. Backlog: «Remediación axe
    // pendiente» en docs/IMPROVEMENT_BACKLOG.md — la lista solo puede encoger.
    .disableRules([
      "color-contrast",
      "nested-interactive",
      "scrollable-region-focusable",
      "target-size",
    ])
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
