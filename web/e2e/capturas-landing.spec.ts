import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";
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
 * Se capturan **los dos ficheros que la portada importa hoy**, en oscuro. La
 * variante clara —servirla con un `<source media="(prefers-color-scheme: dark)">`
 * para que quien tiene el sistema en claro no vea una consola oscura— es el paso
 * siguiente y no se anticipa aquí: añadir al repositorio dos `.webp` que ningún
 * import consume es peso muerto, y el orden correcto es generarlos y usarlos en
 * el mismo cambio. Cuando toque, esta constante crece y `CapturaProducto` gana
 * un `<source>`.
 *
 * El recorte estrecho no es la misma imagen reducida: una consola de escritorio
 * a 375 px deja el texto de la tabla por debajo de 2 px. Se captura el panel de
 * detalle, que es estrecho por naturaleza y cuenta la misma historia.
 */

const DESTINO = path.resolve(__dirname, "..", "src", "app", "(publico)", "_assets");

/** Mismos anchos que `responsive.spec.ts`, para no inventar un tercer juego. */
const ESCRITORIO = { width: 1440, height: 900 };
const MOVIL = { width: 375, height: 812 };

/** Calidad alta pero con pérdida: son capturas de interfaz, no fotografía, y
 *  el peso viaja en el LCP de la portada. Los ficheros anteriores rondaban los
 *  150 KB y 41 KB; conviene no alejarse de ahí. */
const WEBP = { quality: 82 } as const;

async function guardarWebp(png: Buffer, nombre: string): Promise<void> {
  await mkdir(DESTINO, { recursive: true });
  const webp = await sharp(png).webp(WEBP).toBuffer();
  await writeFile(path.join(DESTINO, nombre), webp);
}

test.describe("Capturas de la landing", () => {
  test.skip(!process.env.CAPTURAS, "Herramienta, no test: se ejecuta con CAPTURAS=1");
  test.skip(({ browserName }) => browserName !== "chromium", "Una sola familia de capturas");

  test("bandeja del Radar", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.setViewportSize(ESCRITORIO);
    await page.goto("/radar");

    // La fila del expediente con histórico: sin ella la bandeja podría estar
    // aún cargando y la captura saldría con esqueletos.
    await page.getByText(SEED_LICITACION.tituloRadar).first().waitFor();
    // Abrir su panel de detalle, que es la mitad derecha de la composición.
    await page.getByText(SEED_LICITACION.tituloRadar).first().click();
    await page.getByText("Desglose de score").waitFor();

    const png = await page.screenshot({ animations: "disabled" });
    await guardarWebp(png, "radar-hero.webp");
  });

  test("recorte estrecho del detalle", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.setViewportSize(MOVIL);
    await page.goto(`/detalle?lic=${SEED_LICITACION.radarId}`);
    await page.getByText("Desglose de score").waitFor();

    const png = await page.screenshot({ animations: "disabled" });
    await guardarWebp(png, "radar-hero-movil.webp");
  });
});
