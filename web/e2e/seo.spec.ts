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

    // Lo que importa es que apunte a la **raíz**, no a una subruta. No se
    // afirma la barra final: Next serializa el canonical de la raíz como el
    // origen pelado (`https://sitio`), y para Google esa URL y `https://sitio/`
    // son la misma. Anclar la barra ataba el test a un detalle del framework.
    const canonical = await page.locator('link[rel="canonical"]').getAttribute("href");
    expect(canonical).toBeTruthy();
    expect(new URL(canonical ?? "").pathname).toBe("/");
  });

  test("la portada declara los datos estructurados que se ven en la página", async ({ page }) => {
    await page.goto("/");

    const bruto = await page.locator('script[type="application/ld+json"]').textContent();
    expect(bruto).toBeTruthy();

    const grafo = JSON.parse(bruto ?? "{}");
    const tipos = (grafo["@graph"] ?? []).map((n: { "@type": string }) => n["@type"]);
    expect(tipos).toContain("Organization");
    expect(tipos).toContain("FAQPage");

    // Marcar como FAQ preguntas que no están visibles infringe las directrices
    // de Google. Cada pregunta del JSON-LD tiene que existir en el HTML.
    const faq = (grafo["@graph"] ?? []).find((n: { "@type": string }) => n["@type"] === "FAQPage");
    const preguntas: string[] = (faq?.mainEntity ?? []).map((q: { name: string }) => q.name);
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
    // Las tres páginas de evidencia estuvieron publicadas y bloqueadas a la vez:
    // escritas, desplegadas y fuera del robots, del sitemap y del proxy.
    for (const ruta of ["/cobertura", "/metodologia", "/seguridad"]) {
      expect(body, `${ruta} tiene que ser rastreable`).toContain(`Allow: ${ruta}`);
    }
    expect(body).toContain("Disallow: /");
    expect(body).toContain("Sitemap:");
  });

  test("las páginas de evidencia se sirven sin sesión", async ({ page }) => {
    // El fallo que cazan: al no estar declaradas públicas, el proxy respondía
    // 307 a /login y el visitante anónimo —el público entero de esta
    // superficie— no podía abrirlas.
    for (const ruta of ["/cobertura", "/metodologia", "/seguridad"]) {
      const respuesta = await page.goto(ruta);
      expect(respuesta?.status(), `${ruta} debe servirse`).toBe(200);
      expect(new URL(page.url()).pathname, `${ruta} no puede acabar en /login`).toBe(ruta);
      await expect(page.locator("h1")).toBeVisible();
    }
  });

  test("una URL pública inexistente da un 404 con salida", async ({ page }) => {
    // El 404 subía al de la raíz, cuyo único botón llevaba a /resumen: un 307 a
    // /login para quien acababa de llegar desde un buscador.
    const respuesta = await page.goto("/licitaciones/comunidad-que-no-existe");
    expect(respuesta?.status()).toBe(404);
    await expect(page.locator('a[href="/cpv"]').first()).toBeVisible();
    await expect(page.locator('a[href="/resumen"]')).toHaveCount(0);
  });

  test("el indice de sitemaps existe y enumera ficheros que se sirven", async ({ request }) => {
    // `robots.txt` anuncia esta URL. Con `generateSitemaps`, Next publica
    // `/sitemap/N.xml` pero NO crea indice: `/sitemap.xml` da 404. Si alguien
    // vuelve a apuntar el robots ahi, Search Console lo reporta como error de
    // cobertura y nadie se entera hasta semanas despues.
    const indice = await request.get("/sitemap-index.xml", { maxRedirects: 0 });
    expect(indice.status()).toBe(200);

    const xml = await indice.text();
    expect(xml).toContain("<sitemapindex");

    // Cada fichero anunciado tiene que existir de verdad.
    const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
    expect(locs.length).toBeGreaterThan(0);
    for (const loc of locs) {
      const fichero = await request.get(new URL(loc).pathname, { maxRedirects: 0 });
      expect(fichero.status(), `${loc} anunciado en el indice`).toBe(200);
    }
  });

  test("robots abre solo los prefijos publicos", async ({ request }) => {
    const body = await (await request.get("/robots.txt")).text();
    for (const prefijo of ["/licitaciones", "/cpv", "/aviso-legal"]) {
      expect(body).toContain(`Allow: ${prefijo}`);
    }
    expect(body).toContain("Sitemap: ");
    // La politica es allowlist: bloquear todo y abrir lo publico. Si alguien la
    // invierte a `Allow: /`, cada pantalla del dashboard queda rastreable.
    expect(body).toContain("Disallow: /");
    expect(body).not.toMatch(/^Allow: \/$/m);
  });

  test("el aviso legal se sirve", async ({ request }) => {
    const res = await request.get("/aviso-legal", { maxRedirects: 0 });
    expect(res.status()).toBe(200);
  });

  test("todos los CTA de acceso llevan al formulario", async ({ page }) => {
    // El acceso es por invitación, así que el CTA principal necesita un
    // destino que funcione siempre. Sus dos versiones anteriores no lo eran:
    // un `mailto:` no hace nada en un escritorio con webmail y dependía de una
    // variable de entorno, y sin ella caía a /login, donde el alta responde
    // 403. Ahora lleva al formulario de la propia página, que persiste la
    // petición en la API.
    //
    // Son tres —header, hero e intermedio— y se comprueban todos: el valor de
    // repartirlos es que ninguno sea el que se quedó apuntando al sitio viejo.
    await page.goto("/");

    const ctas = page.getByRole("link", { name: "Solicita acceso" });

    expect(await ctas.count()).toBeGreaterThanOrEqual(3);
    for (const href of await ctas.evaluateAll((as) => as.map((a) => a.getAttribute("href")))) {
      expect(href).toBe("/#solicitar-acceso");
    }
  });

  test("el header ofrece pedir acceso, no solo iniciar sesión", async ({ page }) => {
    // El header es el CTA más persistente del sitio y llevaba a /login, que
    // para quien llega sin cuenta es un muro: el alta responde 403 y el login
    // con Google es fail-closed sin allowlist. En móvil, donde la nav de
    // secciones está oculta, era además lo único accionable de la cabecera.
    await page.goto("/");

    const header = page.locator("header");

    await expect(header.getByRole("link", { name: "Solicita acceso" })).toBeVisible();
    // Iniciar sesión sigue estando: el cambio es de jerarquía, no de supresión.
    await expect(header.getByRole("link", { name: "Iniciar sesión" })).toBeVisible();
  });

  test("el formulario de solicitud existe y envía a la API pública", async ({ page }) => {
    // El ancla del CTA tiene que llevar a un formulario de verdad, y ese
    // formulario tiene que apuntar al endpoint público: si el `action` se
    // rompe, el CTA vuelve a no llevar a ninguna parte y nada más lo detecta.
    await page.goto("/");

    const formulario = page.locator("form#solicitar-acceso");
    await expect(formulario).toBeVisible();
    await expect(formulario).toHaveAttribute("action", "/api/v1/publico/solicitudes-acceso");
    await expect(formulario).toHaveAttribute("method", /post/i);
    // Sin consentimiento explícito no hay base para guardar el dato, así que
    // la casilla es obligatoria también en el navegador.
    await expect(formulario.locator('input[name="consentimiento"]')).toHaveAttribute("required", "");
    // Un `<form>` no es enfocable, así que sin esto el salto de fragmento
    // movía el scroll pero no el foco: quien pulsaba el CTA con teclado
    // volvía al hero al tabular. Ver el módulo del componente.
    await expect(formulario).toHaveAttribute("tabindex", "-1");
  });

  test("enviar el formulario lleva a la página de gracias", async ({ page }) => {
    // El único endpoint público de escritura no tenía ni un test que lo
    // ejercitara de punta a punta: se comprobaba el `action` del `<form>`, no
    // que enviarlo hiciera algo. Un 303 mal formado, un rewrite roto o un
    // rechazo por origen dejan el embudo muerto sin que nada falle.
    await page.goto("/#solicitar-acceso");

    const formulario = page.locator("form#solicitar-acceso");
    await formulario.locator('input[name="email"]').fill("e2e@tenderflow.example");
    await formulario.locator('input[name="empresa"]').fill("E2E");
    await formulario.locator('input[name="consentimiento"]').check();
    await formulario.locator('button[type="submit"]').click();

    await page.waitForURL(/\/solicitud-recibida/);
    await expect(page.locator("h1")).toHaveText("Solicitud recibida");
    // Un acuse de recibo no es contenido: Google no tiene nada que indexar.
    const robots = await page.locator('meta[name="robots"]').getAttribute("content");
    expect(robots ?? "").toContain("noindex");
  });

  test("un envío sin consentimiento dice qué falta, no un error genérico", async ({ page }) => {
    // El endpoint sabe cuál de las dos comprobaciones falló; hasta ahora las
    // dos colapsaban en el mismo `?estado=error` y la página tenía que decir
    // "revisa el email y la casilla". Quien no sabe en qué se equivocó, y
    // encima ha perdido lo que escribió, no reescribe el formulario.
    //
    // El envío se hace por API y no por UI porque el `required` del navegador
    // impide llegar al servidor sin marcar la casilla — que es justo la
    // primera línea de defensa, y por eso también se verifica arriba.
    const respuesta = await page.request.post("/api/v1/publico/solicitudes-acceso", {
      form: { email: "sin-consentimiento@tenderflow.example" },
      maxRedirects: 0,
    });

    expect(respuesta.status()).toBe(303);
    expect(respuesta.headers()["location"]).toContain("estado=consentimiento");
  });

  test("la portada enlaza a la superficie de datos", async ({ page }) => {
    // Sin estos enlaces, los hubs y las fichas solo existen en el sitemap:
    // rastreables, pero sin que nada les transmita autoridad. Es la diferencia
    // entre que Google los encuentre y que lleguen a rankear.
    await page.goto("/");

    await expect(page.locator('a[href="/licitaciones"]').first()).toBeVisible();
    await expect(page.locator('a[href="/cpv"]').first()).toBeVisible();
  });

  test("los indices de la superficie publica no dan error de servidor", async ({ request }) => {
    // No se afirma 200: con una base sembrada sin volumen suficiente, el indice
    // devuelve 404 a proposito (un indice vacio es contenido delgado). Lo que
    // nunca puede pasar es un 5xx, que es lo que este test fija.
    for (const ruta of ["/licitaciones", "/cpv"]) {
      const res = await request.get(ruta, { maxRedirects: 0 });
      expect(res.status(), `${ruta} no puede dar 5xx`).toBeLessThan(500);
    }
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

    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", /\/login$/);
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
  });

  test("emite las etiquetas que necesitan los unfurlers", async ({ page }) => {
    await page.goto("/login");

    await expect(page.locator('meta[property="og:title"]')).toHaveCount(1);
    await expect(page.locator('meta[property="og:image"]')).toHaveCount(1);
    await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute("content", "summary_large_image");

    // `og:image` debe ser absoluta o ningún unfurler la resuelve: eso es lo que
    // aporta `metadataBase` en `app/layout.tsx`.
    const ogImage = await page.locator('meta[property="og:image"]').getAttribute("content");
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
