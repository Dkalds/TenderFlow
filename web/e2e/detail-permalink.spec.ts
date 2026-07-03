import { test, expect } from "@playwright/test";

/**
 * Permalink del panel de detalle: /detalle?lic=<id_externo>.
 *
 * Sin backend/auth el panel no puede poblarse, así que esto es un smoke test
 * del cableado del deep-link (nuqs useQueryState): la carga directa con ?lic=
 * no debe producir errores de JS/React ni perder el parámetro de la URL.
 * La apertura por clic de fila y el botón "Copiar enlace" se cubren en
 * src/components/__tests__/detail-panel.test.tsx y verificación manual.
 */
test.describe("Detail permalink", () => {
  test("loading /detalle?lic= keeps the param and throws no JS errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/detalle?lic=TEST-PERMALINK-1", { waitUntil: "networkidle" });

    const url = page.url();
    const isOnLogin = url.includes("/login");
    if (!isOnLogin) {
      // El deep-link no debe ser tragado por la página al montar.
      expect(url).toContain("lic=TEST-PERMALINK-1");
    }

    const unexpectedErrors = errors.filter(
      (e) =>
        !e.includes("fetch") &&
        !e.includes("Failed to fetch") &&
        !e.includes("NetworkError") &&
        !e.includes("server responded") &&
        !e.includes("500") &&
        !e.includes("404") &&
        !e.includes("Content-Security-Policy") &&
        !e.includes("content-security-policy") &&
        !e.includes("Content Security Policy") &&
        !e.includes("Report Only") &&
        !e.includes("Refused to load")
    );
    expect(unexpectedErrors).toHaveLength(0);
  });
});
