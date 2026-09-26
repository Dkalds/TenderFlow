import { test, expect } from "@playwright/test";
import { SEED_LICITACION, SEED_PREFIX } from "./fixtures";

/**
 * Navegación móvil real (cierra el [P1] de docs/IMPROVEMENT_BACKLOG.md).
 *
 * Los dos tests anteriores solo afirmaban `expect(body).toBeVisible()`. El
 * primero llegaba a construir un localizador del hamburguesa con tres
 * estrategias encadenadas y **nunca lo usaba** — el prefijo `_` existía para
 * callar al linter. Es decir: la única cobertura declarada de la experiencia
 * móvil pasaba con la navegación completamente rota, y por debajo de `md` la
 * sidebar es `hidden md:flex`, así que el drawer es la única forma de cambiar
 * de sección.
 *
 * Estos tests fallan si se elimina el drawer: sin `.or()`, sin `if`, sin
 * `.catch()`.
 *
 * La navegación era, además, lo único que se cubría: el **contenido** seguía
 * siendo de escritorio. El Radar era una tabla de siete columnas con 666 px de
 * ancho mínimo, así que a 375 px la acción quedaba a dos pantallazos de scroll
 * horizontal del título. Los tests de abajo miden eso donde se puede medir —un
 * navegador con layout real— porque en jsdom no hay ni anchos ni media queries.
 */

const MOVIL = { width: 375, height: 812 };
const ESCRITORIO = { width: 1440, height: 900 };

async function expectDocumentFits(page: import("@playwright/test").Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

/**
 * En el dashboard el documento no scrollea nunca en alto: el marco mide el
 * viewport y cada pantalla desplaza su propia caja.
 *
 * Lo rompe un `absolute` sin ancestro posicionado dentro de esa caja —un
 * `sr-only`, los `<select>` nativos que Radix pinta en los formularios—: su
 * bloque contenedor pasa a ser el viewport, la caja no lo recorta y alarga el
 * documento. La rueda sobre la cabecera o el rail bajaba entonces la página
 * entera hacia una franja en blanco (la ficha de oportunidad llegó a medir
 * 1356 px a 1366×768). De ahí el `relative` de cada caja con scroll; ver
 * `space-shell.tsx`.
 *
 * Va aparte de `expectDocumentFits` porque las páginas públicas son largas a
 * propósito. La ficha de oportunidad, donde más se notaba, no se mide aquí:
 * la semilla E2E no crea ninguna.
 */
async function expectDocumentFitsVertically(page: import("@playwright/test").Page) {
  const sobrante = await page.evaluate(
    () => document.documentElement.scrollHeight - document.documentElement.clientHeight,
  );
  expect(sobrante).toBeLessThanOrEqual(1);
}

/**
 * Con la barra de ámbito llena, lo que se desplaza es la barra: el contenedor
 * de chips no encoge por debajo de su contenido. Con `min-w-0` era el único
 * hijo que cedía ancho (sus hermanos son `flex-none`), y los chips y
 * «+ Añadir» se le salían por encima de lo que venía detrás.
 */
async function expectChipsDelAmbitoSinSolape(page: import("@playwright/test").Page) {
  const barra = page.locator('[data-slot="barra-ambito"]');
  const chips = barra.locator('[data-slot="ambito-chips"]');
  await expect(chips.getByRole("button", { name: "+ Añadir" })).toBeVisible();

  const { recorte, solape } = await chips.evaluate((el) => {
    const anadir = [...el.querySelectorAll("button")].at(-1)!.getBoundingClientRect();
    const siguiente = el.nextElementSibling!.getBoundingClientRect();
    return { recorte: el.scrollWidth - el.clientWidth, solape: anadir.right - siguiente.left };
  });
  expect(recorte).toBeLessThanOrEqual(1);
  expect(solape).toBeLessThanOrEqual(0.5);

  // Y la barra se desplaza de verdad: si cupiera, no habría nada que encoger y
  // lo de arriba pasaría en vacío.
  const desplazamiento = await barra.evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(desplazamiento).toBeGreaterThan(0);
}

/**
 * La superficie pública, a los tres anchos.
 *
 * No estaba cubierta: los tests de abajo miden el dashboard, que es donde vive
 * el problema histórico de las tablas anchas. Pero la portada es la única
 * página que ve alguien que no ha entrado nunca, y un scroll horizontal ahí se
 * paga en la primera pantalla. Sin sesión, porque con cookie `/` redirige.
 */
test.describe("Superficie pública sin sesión", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  for (const viewport of [MOVIL, { width: 768, height: 1024 }, ESCRITORIO]) {
    test(`la portada cabe a ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto("/");
      await expect(page.locator("h1")).toBeVisible();
      await expectDocumentFits(page);
    });
  }

  test("en móvil el header ofrece navegación, no solo el logo", async ({ page }) => {
    // La nav de secciones era `hidden … sm:flex` sin alternativa: por debajo de
    // 640px, las dos páginas que reparten autoridad interna hacia los hubs
    // desaparecían del chrome y solo quedaban los dos botones de acceso.
    await page.setViewportSize(MOVIL);
    await page.goto("/");

    await expect(page.locator('header a[href="/licitaciones"]')).toBeVisible();
    await expect(page.locator('header a[href="/cpv"]')).toBeVisible();
  });
});

test.describe("Móvil (375×812)", () => {
  test.use({ viewport: MOVIL });

  test("el drawer es la vía de navegación y abre con enlaces utilizables", async ({ page }) => {
    await page.goto("/resumen");

    // El rail de espacios (la navegación de escritorio) es `md:flex`: por
    // debajo de ese ancho no existe, y el drawer es la única alternativa.
    await expect(page.getByRole("navigation", { name: "Espacios" })).toBeHidden();

    const hamburguesa = page.getByRole("button", { name: "Abrir navegación" });
    await expect(hamburguesa).toBeVisible();

    await hamburguesa.click();

    const drawer = page.getByRole("dialog");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("navigation", { name: /navegación móvil/i })).toBeVisible();
  });

  test("navegar desde el drawer cambia de página y lo cierra", async ({ page }) => {
    await page.goto("/resumen");
    await page.getByRole("button", { name: "Abrir navegación" }).click();

    const drawer = page.getByRole("dialog");
    // Un destino concreto, no "algún enlace": si el menú se queda vacío o deja
    // de navegar, el test tiene que caer.
    await drawer.getByRole("link", { name: /Radar/ }).first().click();

    await expect(page).toHaveURL(/\/radar/);
    await expect(drawer).toBeHidden();
  });

  test("la barra móvil va encima del contenido y la pantalla cabe en alto", async ({ page }) => {
    // El marco era una fila también en móvil: la barra quedaba como una
    // columna de ~181px a la izquierda y el contenido se estrujaba en ~194px.
    // Las medidas de desborde no lo veían porque nada desbordaba: miden el
    // ancho del documento, no el del contenido.
    await page.goto("/radar");
    await expect(page.getByText(SEED_LICITACION.tituloRadar).first()).toBeVisible({
      timeout: 20_000,
    });

    const hamburguesa = await page.getByRole("button", { name: "Abrir navegación" }).boundingBox();
    const contenido = await page.locator("#main-content").boundingBox();
    expect(hamburguesa).not.toBeNull();
    expect(contenido).not.toBeNull();

    expect(contenido!.x).toBeLessThanOrEqual(1);
    expect(contenido!.width).toBeGreaterThanOrEqual(MOVIL.width - 1);
    expect(contenido!.y).toBeGreaterThanOrEqual(hamburguesa!.y + hamburguesa!.height);
    // Las pantallas miden `100vh - var(--alto-cromo)`, que por debajo de `md`
    // cuenta también los 48px de la barra móvil: sin ellos, cada pantalla
    // acababa esos 48px por debajo del pliegue.
    expect(contenido!.y + contenido!.height).toBeLessThanOrEqual(MOVIL.height + 1);
    // Que `#main-content` quepa no basta: un absoluto de la lista que cuelgue
    // del viewport alarga el documento sin mover ninguna caja.
    await expectDocumentFitsVertically(page);
  });

  test("el Resumen no alarga el documento con los `sr-only` de sus filas", async ({ page }) => {
    // Las filas del Resumen llevan texto `sr-only` («Nueva desde tu última
    // visita.», «Oportunidad · Plazo de presentación:»). Sin `relative` en el
    // cuerpo con scroll colgaban del viewport: a 375×812 el documento medía
    // 29 px de más. Se espera a una fila real del seed: sin filas no hay nada
    // que desborde y la medida daría verde en falso.
    await page.goto("/resumen");
    await expect(page.locator(`a[href^="/detalle?lic=${SEED_PREFIX}"]`).first()).toBeVisible({
      timeout: 20_000,
    });

    await expectDocumentFitsVertically(page);
  });

  test("el Radar cabe a lo ancho: ni la lista ni la página desbordan", async ({ page }) => {
    await page.goto("/radar");
    // Sin una fila real no hay nada que pueda desbordar y la medida daría verde
    // con la tabla intacta: se espera a un expediente concreto del seed.
    await expect(page.getByText(SEED_LICITACION.tituloRadar).first()).toBeVisible({
      timeout: 20000,
    });

    // La lista tiene `overflow-y-auto`, y por CSS eso vuelve `auto` también el
    // eje X: una tabla de siete columnas se le desborda dentro sin que el body
    // se entere. Es la medida que de verdad delata el escritorio plegado, así
    // que va primera.
    const desbordeLista = await page
      .locator('[data-slot="radar-lista"]')
      .evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(desbordeLista).toBeLessThanOrEqual(1);

    // El contenedor con scroll de la aplicación (`<main id="main-content">`) y,
    // por último, el documento: aquí caía la cabecera de columnas, que vivía
    // fuera de la lista.
    const desbordeMain = await page
      .locator("#main-content")
      .evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(desbordeMain).toBeLessThanOrEqual(1);

    const desbordeDocumento = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(desbordeDocumento).toBeLessThanOrEqual(1);
  });

  test("descartar y abrir una señal se pulsan sin seleccionarla ni buscarlas", async ({ page }) => {
    await page.goto("/radar");
    await expect(page.getByText(SEED_LICITACION.tituloRadar).first()).toBeVisible({
      timeout: 20000,
    });

    // En escritorio estas acciones aparecen al seleccionar la fila. En táctil no
    // hay hover, así que tienen que estar visibles de entrada: se mira la
    // primera fila **sin haberla tocado**.
    const acciones = page.locator('[data-slot="radar-acciones"]').first();
    await expect(acciones).toBeVisible();

    const abrir = acciones.getByRole("button", { name: "Abrir" });
    const descartar = acciones.getByRole("button", { name: /^Descartar / });

    // WCAG 2.5.8 pide 24×24 px reales; la ficha móvil va a 36 y se comprueba
    // que no se quede por debajo del mínimo si alguien la reajusta.
    for (const boton of [abrir, descartar]) {
      await expect(boton).toBeVisible();
      await expect(boton).toBeInViewport();
      const caja = await boton.boundingBox();
      expect(caja).not.toBeNull();
      expect(caja!.width).toBeGreaterThanOrEqual(24);
      expect(caja!.height).toBeGreaterThanOrEqual(24);
    }
  });

  test("la ficha de una licitación se consulta sin desbordar la página", async ({ page }) => {
    await page.goto(`/detalle?lic=${SEED_LICITACION.id}`);
    await expect(page.getByText(SEED_LICITACION.titulo).first()).toBeVisible({ timeout: 20_000 });

    await expectDocumentFits(page);
    await expectDocumentFitsVertically(page);
  });

  test("watchlist mantiene visibles sus dos modos de trabajo", async ({ page }) => {
    // Los 274 px de desborde no eran de la watchlist sino de la barra de
    // ámbito en su rama «no aplica» (sin `overflow-x-auto`, ~650 px de
    // rótulo y utilidades). Arreglada la barra, el `fixme` sale (2026-09-18).
    await page.goto("/mi-watchlist");
    const reglas = page.getByRole("tab", { name: "Reglas" });
    const favoritos = page.getByRole("tab", { name: "Favoritos" });

    for (const tab of [reglas, favoritos]) {
      await expect(tab).toBeVisible();
      await expect(tab).toBeInViewport();
      const box = await tab.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.height).toBeGreaterThanOrEqual(24);
    }
    await expectDocumentFits(page);
    await expectDocumentFitsVertically(page);
  });

  test("la agenda usa fichas móviles y no desborda el documento", async ({ page }) => {
    // Las fichas móviles de la agenda existen (`agenda-fila.tsx`, `md:contents`)
    // y el desborde que quedaba era el mismo de la barra de ámbito que el test
    // de la watchlist. `fixme` retirado el 2026-09-18.
    //
    // El texto se ancla al recuento del carril («N en este carril»), que solo
    // aparece con la agenda ya cargada (antes dice «Cargando agenda…») y
    // también cuando está vacía («0 en este carril»). Un `/compromisos/` suelto
    // resolvía primero a la descripción del espacio («Tus compromisos,
    // ordenados…»), que es `hidden xl:inline` en la cabecera: el test esperaba
    // 20 s a que se viera algo que a 375 px está oculto a propósito.
    //
    // Hasta el 2026-09-24 el ancla era «N compromisos» o «Tu agenda está
    // vacía»: los dos textos desaparecieron con el rediseño de la Agenda en
    // dos carriles (#330), cuyo E2E no llegó a correr, y el siguiente PR que lo
    // ejecutó (#332) cayó aquí.
    await page.goto("/mi-pipeline");
    await expect(page.locator('[data-slot="agenda-filas"]')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/^[\d.]+ en este carril$/).first()).toBeVisible({
      timeout: 20_000,
    });

    await expectDocumentFits(page);
    await expectDocumentFitsVertically(page);
  });

  test("la barra de ámbito se desplaza sin que los chips encojan ni pisen lo siguiente", async ({ page }) => {
    // A 375 px la barra no cabe ni sin chips: el contenedor caía a 0 px y
    // «+ Añadir» se pintaba encima del aviso y del recuento. El chip y el
    // filtro que el Radar no aplica salen de la URL, no del seed.
    await page.goto("/radar?tecnologia=SAP&ccaa=Madrid");
    await expectChipsDelAmbitoSinSolape(page);
    await expectDocumentFits(page);
  });

  test("el aviso de «no aplica» cabe en la barra en una sola línea", async ({ page }) => {
    // Con un filtro activo en una pantalla que no lo aplica, el aviso encogía
    // hasta su palabra más larga: nueve líneas (144 px) en una barra de 52,
    // que las recortaba —se leía «no aplica en esta»— y se desplazaba en
    // vertical.
    await page.goto("/mi-watchlist?ccaa=Madrid");
    const barra = page.locator('[data-slot="barra-ambito"]');
    await expect(barra.getByText(/El ámbito global no aplica en esta pantalla/)).toBeVisible();

    const desbordeVertical = await barra.evaluate((el) => el.scrollHeight - el.clientHeight);
    expect(desbordeVertical).toBeLessThanOrEqual(1);
    await expectDocumentFits(page);
  });
});

/**
 * Poco alto: un portátil de 1366×768 con el escalado de Windows al 125 % deja
 * un viewport de ~1093×520. El rail entra en scroll, y el rótulo `sr-only` de
 * cada destino colgaba del `<nav>` y no de esa caja: los últimos caían bajo el
 * pliegue y el documento scrolleaba (605 px a 1280×600 con los 16 espacios de
 * un administrador). El usuario demo ve 14; con el mismo espaciado, su último
 * rótulo queda hacia y=541, bajo los 520 de este viewport.
 *
 * Se mide en Mi Watchlist porque no aplica el ámbito. En las pantallas que sí,
 * la franja de primer uso de la barra (`ambito-intro.tsx`), que el E2E no
 * cierra, suma su alto al documento: es otro desborde, y no de un absoluto.
 */
test.describe("Poco alto (1100×520)", () => {
  test.use({ viewport: { width: 1100, height: 520 } });

  test("los rótulos del rail no alargan el documento", async ({ page }) => {
    await page.goto("/mi-watchlist");
    await expect(page.getByRole("navigation", { name: "Espacios" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Reglas" })).toBeVisible({ timeout: 20_000 });

    await expectDocumentFitsVertically(page);
  });
});

/**
 * La franja `md`–`xl`, donde el inspector es un `Sheet` y cada fila lleva un
 * cuarto botón («Ver ficha»). El E2E de accesibilidad corre a 1280, que ya es
 * `xl` y enseña tres: el desborde de esta franja no lo veía nadie.
 */
test.describe("Tableta horizontal (1024×768)", () => {
  test.use({ viewport: { width: 1024, height: 768 } });

  test("las acciones de la fila activa caben en su columna y no pisan Plazo", async ({ page }) => {
    await page.goto("/radar");
    // `[data-active]` solo lo emite `radar-fila.tsx`; ver `seleccionarFila` en
    // critical-workflows.spec.ts. Hay que seleccionarla: las acciones de una
    // fila inactiva son `inert` y no están en el árbol de accesibilidad.
    const fila = page.locator("[data-active]").filter({ hasText: SEED_LICITACION.tituloRadar }).first();
    await expect(fila).toBeVisible({ timeout: 20_000 });
    await fila.locator('[data-slot="radar-fila-seleccion"]').click();
    await expect(fila).toHaveAttribute("data-active", "true");

    const acciones = fila.locator('[data-slot="radar-acciones"]');
    // Sin el cuarto botón la medida pasaría con la columna de 116 px de `xl`.
    await expect(acciones.getByRole("button", { name: /^Ver ficha de / })).toBeVisible();
    // Esperar a que acabe el `slide-in-from-right` de la fila activa: con el
    // `translate` a medias las cajas salen corridas.
    await acciones.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));

    // La celda es el propio bloque: es hijo directo de la rejilla y toma el
    // ancho de la pista. El desborde de `justify-end` sale por la izquierda,
    // que `scrollWidth` no cuenta, así que se comparan cajas.
    const celda = await acciones.boundingBox();
    expect(celda).not.toBeNull();
    const botones = acciones.getByRole("button");
    await expect(botones).toHaveCount(4);
    for (const boton of await botones.all()) {
      const caja = await boton.boundingBox();
      expect(caja).not.toBeNull();
      expect(caja!.x).toBeGreaterThanOrEqual(celda!.x - 0.5);
      expect(caja!.x + caja!.width).toBeLessThanOrEqual(celda!.x + celda!.width + 0.5);
      // WCAG 2.5.8 / axe `target-size`: que el arreglo no sea encoger botones.
      expect(caja!.width).toBeGreaterThanOrEqual(24);
      expect(caja!.height).toBeGreaterThanOrEqual(24);
    }
  });
});

test.describe("Escritorio (1440×900)", () => {
  test.use({ viewport: ESCRITORIO });

  test("el rail de espacios sustituye al hamburguesa", async ({ page }) => {
    await page.goto("/resumen");

    await expect(page.getByRole("navigation", { name: "Espacios" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Abrir navegación" })).toBeHidden();
  });

  test("con el ámbito lleno, la barra se desplaza en vez de montar los chips encima", async ({ page }) => {
    // También en escritorio: con cinco chips en Resumen el contenedor encogía y
    // los chips tapaban el recuento, «Vistas» y parte de «Buscar». Van seis, y
    // salen de la URL, no del seed: sobra margen para que la barra no quepa
    // aunque el recuento y el «sync» midan distinto con otros datos.
    const ambito = new URLSearchParams({
      q: "mantenimiento evolutivo del ERP",
      ccaa: "Madrid,Galicia,Cantabria",
      tecnologia: "SAP",
      importe_min: "100000",
    });
    await page.goto(`/resumen?${ambito}`);
    await expectChipsDelAmbitoSinSolape(page);
    await expectDocumentFits(page);
  });
});
