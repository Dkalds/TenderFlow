import { test, expect } from "@playwright/test";

/**
 * Guard de la superficie pública y de SEO.
 *
 * Existe por un fallo concreto y fácil de reintroducir: el matcher de
 * `src/middleware.ts` sólo excluye `/api`, `/_next/static`, `/_next/image` y
 * `favicon.ico`, así que `robots.txt`, `sitemap.xml` y las rutas de imagen de
 * metadatos pasan por el control de sesión. Hasta que se añadieron a
 * `PUBLIC_PREFIXES` devolvían un 307 a `/login`, con dos consecuencias
 * invisibles desde dentro del producto: Google no podía leer el robots, y el
 * unfurler de Slack/LinkedIn/WhatsApp recibía la pantalla de login en lugar de
 * la imagen Open Graph, de modo que cada enlace compartido salía sin preview.
 *
 * Un `PUBLIC_PREFIXES` reordenado o un matcher retocado lo rompen sin que falle
 * ningún otro test. De ahí que cada bloque compruebe el par completo: lo
 * público responde 200 **y** el dashboard sigue cerrado. La segunda mitad
 * importa tanto como la primera — una exención demasiado ancha (meter `"/"`
 * entre los prefijos, sin ir más lejos) abriría el producto entero.
 */

const SIN_SESION = { storageState: { cookies: [], origins: [] } };

test.describe("Superficie pública sin sesión", () => {
  test.use(SIN_SESION);

  test("la portada se sirve y es indexable", async ({ page }) => {
    const res = await page.goto("/");

    expect(res?.status()).toBe(200);
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h1")).not.toBeEmpty();

    // El layout raíz marca `noindex` para toda la app; el grupo `(publico)`
    // tiene que revertirlo o la landing no llega al índice.
    const robots = await page
      .locator('meta[name="robots"]')
      .getAttribute("content")
      .catch(() => null);
    expect(robots ?? "").not.toContain("noindex");

    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      /\/$/,
    );
  });

  test("la portada declara los datos estructurados que se ven en la página", async ({
    page,
  }) => {
    await page.goto("/");

    const bruto = await page.locator('script[type="application/ld+json"]').textContent();
    expect(bruto).toBeTruthy();

    const grafo = JSON.parse(bruto ?? "{}");
    const tipos = (grafo["@graph"] ?? []).map((n: { "@type": string }) => n["@type"]);
    expect(tipos).toContain("Organization");
    expect(tipos).toContain("FAQPage");

    // Marcar como FAQ preguntas que no están visibles infringe las directrices
    // de Google. Cada pregunta del JSON-LD tiene que existir en el HTML.
    const faq = (grafo["@graph"] ?? []).find(
      (n: { "@type": string }) => n["@type"] === "FAQPage",
    );
    const preguntas: string[] = (faq?.mainEntity ?? []).map(
      (q: { name: string }) => q.name,
    );
    expect(preguntas.length).toBeGreaterThan(0);
    for (const pregunta of preguntas) {
      await expect(page.getByText(pregunta, { exact: true })).toBeVisible();
    }
  });

  test("robots.txt abre la portada y bloquea el dashboard", async ({ request }) => {
    const res = await request.get("/robots.txt", { maxRedirects: 0 });
    expect(res.status()).toBe(200);

    const body = await res.text();
    // El `$` ancla el final de la URL: abre `/` sin arrastrar `/resumen`.
    expect(body).toContain("Allow: /$");
    // `/login` rastreable a propósito: bloqueada por robots, Google no podría
    // leer su `noindex` y nunca la sacaría del índice.
    expect(body).toContain("Allow: /login");
    expect(body).toContain("Disallow: /");
    expect(body).toContain("Sitemap:");
  });

  test("el sitemap se sirve y anuncia la portada", async ({ request }) => {
    const res = await request.get("/sitemap.xml", { maxRedirects: 0 });

    expect(res.status()).toBe(200);
    expect(await res.text()).toContain("<loc>");
  });

  test("la imagen Open Graph se sirve como PNG", async ({ request }) => {
    const res = await request.get("/opengraph-image", { maxRedirects: 0 });

    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("image/png");
  });

  test("el manifest se sirve", async ({ request }) => {
    const res = await request.get("/manifest.webmanifest", { maxRedirects: 0 });

    expect(res.status()).toBe(200);
  });

  test("el dashboard sigue exigiendo sesión", async ({ request }) => {
    const res = await request.get("/resumen", { maxRedirects: 0 });

    expect(res.status()).toBe(307);
    expect(res.headers()["location"]).toContain("/login");
  });
});

test.describe("Metadatos de /login", () => {
  test.use(SIN_SESION);

  test("declara noindex y un canonical que colapsa las variantes", async ({ page }) => {
    // El middleware manda aquí desde cada ruta del dashboard con un `?redirect=`
    // distinto; sin canonical serían decenas de URLs con el mismo contenido.
    await page.goto("/login?redirect=%2Fresumen");

    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      /\/login$/,
    );
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
      "content",
      /noindex/,
    );
  });

  test("emite las etiquetas que necesitan los unfurlers", async ({ page }) => {
    await page.goto("/login");

    await expect(page.locator('meta[property="og:title"]')).toHaveCount(1);
    await expect(page.locator('meta[property="og:image"]')).toHaveCount(1);
    await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute(
      "content",
      "summary_large_image",
    );

    // `og:image` debe ser absoluta o ningún unfurler la resuelve: eso es lo que
    // aporta `metadataBase` en `app/layout.tsx`.
    const ogImage = await page
      .locator('meta[property="og:image"]')
      .getAttribute("content");
    expect(ogImage).toMatch(/^https?:\/\//);
  });
});

/**
 * Este bloque usa el `storageState` autenticado que inyecta el proyecto por
 * defecto: comprueba que abrir la portada con sesión no deja al usuario en el
 * marketing, sino donde aterrizaba antes de que `/` cambiara de dueño.
 */
test.describe("La portada con sesión iniciada", () => {
  test("lleva al dashboard, no a la landing", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveURL(/\/resumen/);
  });
});
