import { test, expect } from "@playwright/test";
import { SEED_LICITACION } from "./fixtures";

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
});

test.describe("Escritorio (1440×900)", () => {
  test.use({ viewport: ESCRITORIO });

  test("el rail de espacios sustituye al hamburguesa", async ({ page }) => {
    await page.goto("/resumen");

    await expect(page.getByRole("navigation", { name: "Espacios" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Abrir navegación" })).toBeHidden();
  });
});
