import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { test } from "@playwright/test";
import { SEED_LICITACION } from "./fixtures";

/**
 * Regenera las capturas del producto que enseña la landing.
 *
 * Existe porque no existía. Los `.webp` de `app/(publico)/_assets/` se tomaron
 * a mano en agosto de 2026 y desde entonces el producto siguió cambiando sin
 * que nada lo notara. Lo que quedó publicado en la portada durante semanas es
 * un buen resumen del problema: un aviso amarillo de «Score degradado», dos
 * chips con identificadores en crudo del backend (`sin_historico_competencia`,
 * `sin_senal_tecnica`), un panel que decía «ADR-014 · backend» —la referencia
 * interna de una decisión de arquitectura— y un órgano sin adjudicaciones
 * registradas. Todo cierto, todo interno, y todo enseñado como el mejor
 * escaparate del producto.
 *
 * No es un test: no afirma nada. Es una herramienta que vive en `e2e/` porque
 * así hereda gratis lo que necesita —el servidor de `playwright.config.ts`, la
 * sesión de `auth.setup.ts` y los expedientes deterministas de
 * `scripts/seed_dev.py`— en vez de reimplementar login y arranque en un script
 * suelto. Por eso se salta salvo que se pidan explícitamente las capturas:
 *
 *     CAPTURAS=1 npx playwright test capturas-landing --project=chromium
 *
 * o `npm run capturas:landing`, que es lo mismo. Requiere el stack completo
 * levantado (Postgres sembrado + API + `npm run dev`).
 *
 * ## Qué se captura, y por qué así
 *
 * El expediente es `SEED-2026-008`, que el seed siembra con histórico y
 * predicción: no arrastra avisos de señal ausente, así que la bandeja se ve en
 * su estado normal y no en el degradado. Si el seed cambia y vuelven los
 * avisos, se ve aquí antes que en producción.
 *
 * El tema se fuerza con `emulateMedia` y no tocando `localStorage`: los dos
 * providers de la app son `next-themes` con `defaultTheme="system"`, así que
 * emular la preferencia del sistema es exactamente lo que hará el navegador de
 * un visitante.
 *
 * Se capturan los dos recortes en **los dos temas**: `radar-hero.webp` y
 * `radar-hero-movil.webp` (oscuro) y sus variantes `-claro`
 * (`radar-hero-claro.webp`, `radar-hero-movil-claro.webp`).
 * `CapturaProducto` las sirve con `<source media="(prefers-color-scheme: dark)">`
 * para que quien tiene el sistema en claro no vea una consola oscura. Importa
 * los cuatro ficheros: borrar uno rompe el build.
 *
 * El recorte estrecho no es la misma imagen reducida: una consola de escritorio
 * a 375 px deja el texto de la tabla por debajo de 2 px. Se captura el cuerpo
 * del inspector del Radar (score, banda y desglose), que es estrecho por
 * naturaleza y cuenta la misma historia. Hasta el 2026-11-16 se tomaba de
 * `/detalle` a 375 px esperando «Desglose de score», que ya no vive allí.
 *
 * Con `next dev` la captura saca la insignia de desarrollo de Next: se toma
 * contra `npm run build && npm run start`.
 */

const DESTINO = path.resolve(__dirname, "..", "src", "app", "(publico)", "_assets");

/** Mismo ancho que `responsive.spec.ts`, para no inventar otro. */
const ESCRITORIO = { width: 1440, height: 900 };

/** Calidad alta pero con pérdida: son capturas de interfaz, no fotografía, y
 *  el peso viaja en el LCP de la portada. Los ficheros anteriores rondaban los
 *  150 KB y 41 KB; conviene no alejarse de ahí. */
const WEBP = { quality: 82 } as const;

/**
 * `sharp` se importa aquí dentro y no en la cabecera del módulo.
 *
 * No está declarado en `web/package.json`: llega como dependencia **opcional y
 * transitiva** de `next`. Un `import` de nivel superior lo convertiría en
 * requisito de cargar el fichero, y Playwright carga todos los specs para
 * listarlos — así que un `npm ci --omit=optional`, o una versión de Next que
 * deje de traerlo, rompería el listado de tests y el typecheck por un paquete
 * que nadie declaró. Dentro de la función, el coste lo paga sólo quien ejecuta
 * la herramienta, y el mensaje dice qué hacer.
 */
async function guardarWebp(png: Buffer, nombre: string): Promise<void> {
  let sharp;
  try {
    ({ default: sharp } = await import("sharp"));
  } catch {
    throw new Error(
      "Falta `sharp`, que convierte las capturas a webp. Llega como dependencia " +
        "opcional de next: instálalo con `npm i -D sharp` si tu instalación lo omitió.",
    );
  }
  await mkdir(DESTINO, { recursive: true });
  const webp = await sharp(png).webp(WEBP).toBuffer();
  await writeFile(path.join(DESTINO, nombre), webp);
}

/**
 * Radar con el expediente del seed seleccionado y su inspector abierto.
 *
 * Se selecciona como en `responsive.spec.ts`: por la celda de selección de su
 * fila (`[data-active]` solo lo emite `radar-fila.tsx`), no con un clic en el
 * título, que no abre el inspector. Antes se cierra la franja de primer uso
 * del ámbito, que no forma parte de lo que la portada enseña.
 */
async function abrirInspector(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/radar");
  await page.getByRole("button", { name: "Entendido, no volver a mostrar" }).click();
  const fila = page.locator("[data-active]").filter({ hasText: SEED_LICITACION.tituloRadar }).first();
  await fila.waitFor({ timeout: 20_000 });
  await fila.locator('[data-slot="radar-fila-seleccion"]').click();
  await page.getByText("Desglose de score").waitFor();
}

test.describe("Capturas de la landing", () => {
  test.skip(!process.env.CAPTURAS, "Herramienta, no test: se ejecuta con CAPTURAS=1");
  test.skip(({ browserName }) => browserName !== "chromium", "Una sola familia de capturas");
  // La imagen ocupa hasta 1104 px CSS en la portada: a 1x se vería borrosa en
  // una pantalla de densidad 2. `next/image` sirve después el ancho que toque.
  test.use({ deviceScaleFactor: 2 });

  for (const tema of ["dark", "light"] as const) {
    const sufijo = tema === "light" ? "-claro" : "";

    test(`bandeja del Radar (${tema})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: tema });
      await page.setViewportSize(ESCRITORIO);
      await abrirInspector(page);

      const png = await page.screenshot({ animations: "disabled" });
      await guardarWebp(png, `radar-hero${sufijo}.webp`);
    });

    test(`recorte estrecho del inspector (${tema})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: tema });
      await page.setViewportSize(ESCRITORIO);
      await abrirInspector(page);

      // El inspector desde su cabecera (score, banda y título) hasta el final
      // del desglose. Mide 432 px de ancho, así que no hace falta reducir una
      // pantalla de escritorio. La cabecera queda fuera de la región con
      // scroll, por eso se recorta sobre la columna y no sobre la región.
      const columna = await page
        .getByRole("region", { name: "Detalle de la señal" })
        .locator("..")
        .boundingBox();
      const finDesglose = await page.getByText("Línea de tiempo").boundingBox();
      if (!columna || !finDesglose) throw new Error("No se encontró el inspector del Radar");
      const png = await page.screenshot({
        animations: "disabled",
        clip: { ...columna, height: finDesglose.y - columna.y - 8 },
      });
      await guardarWebp(png, `radar-hero-movil${sufijo}.webp`);
    });
  }
});
