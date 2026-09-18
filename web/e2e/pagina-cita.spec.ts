import { test, expect } from "@playwright/test";
import { SEED_LICITACION } from "./fixtures";

/**
 * F2.5 — «desde la ficha a la página resaltada en dos clics».
 *
 * El seed de E2E (`scripts/seed_dev.py`) no trae fichas de pliego ni texto
 * por página: extraerlas exige descargar PDFs y llamar al LLM, que en CI no
 * hay. Por eso las cuatro lecturas del pliego se sirven con `page.route` y el
 * resto de la pantalla —sesión, detalle, inspector— va contra la API real. Lo
 * que se fija es el recorrido de la interfaz, no la extracción: el contrato de
 * la ruta de páginas tiene sus propios tests en `tests/`.
 */

const ID = SEED_LICITACION.id;
const CITA = "El precio tendrá un peso del 55 %.";
const TEXTO_PAGINA = `Cláusula 12. Criterios de adjudicación. ${CITA} El resto se valora por juicio de valor.`;
const INICIO_REL = TEXTO_PAGINA.indexOf(CITA);

test("desde la ficha del pliego se abre la página con la cita resaltada en dos clics", async ({ page }) => {
  const base = `**/api/v1/licitaciones/${encodeURIComponent(ID)}`;

  await page.route(`${base}/ficha-pliego`, (route) =>
    route.fulfill({
      json: {
        licitacion_id: ID,
        status: "extracted",
        extraction_version: "facts-e2e",
        model: "e2e",
        field_count: 1,
        evidence_count: 1,
        error_detail: null,
        extracted_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
        facts: {
          award_criteria: [
            {
              name: "Precio",
              description: "Oferta económica",
              confidence: 0.9,
              weight_pct: 55,
              evidence: [
                // Offsets absolutos en el documento; la API los devuelve ya
                // relativos a la página (ver la ruta de abajo).
                { documento_id: 7, page_number: 3, quote: CITA, start_offset: 5000, end_offset: 5000 + CITA.length },
              ],
            },
          ],
        },
      },
    }),
  );
  await page.route(`${base}/ficha-pliego/estado`, (route) =>
    route.fulfill({ json: { licitacion_id: ID, running: false } }),
  );
  await page.route(`${base}/documentos`, (route) =>
    route.fulfill({
      json: {
        id_externo: ID,
        items: [{ id: 7, tipo: "legal", uri: "https://placsp.example/pcap.pdf", filename: "PCAP.pdf", status: "extracted" }],
      },
    }),
  );
  await page.route(`${base}/documentos/7/paginas/3*`, (route) =>
    route.fulfill({
      json: {
        documento_id: 7,
        page_number: 3,
        texto: TEXTO_PAGINA,
        total_paginas: 12,
        resaltado_inicio: INICIO_REL,
        resaltado_fin: INICIO_REL + CITA.length,
        resaltado_omitido: null,
        filename: "PCAP.pdf",
        uri: "https://placsp.example/pcap.pdf",
      },
    }),
  );

  await page.goto(`/detalle?lic=${ID}`);
  const ficha = page.getByRole("complementary", { name: "Ficha de la licitación" });
  await expect(ficha).toBeVisible({ timeout: 20000 });
  await ficha.getByRole("tab", { name: "IA" }).click();
  await expect(ficha.getByText("Criterios de adjudicación")).toBeVisible();

  // Clic 1: desplegar las citas del hecho. Clic 2: abrir la página.
  await ficha.getByText("1 cita verificable").click();
  await ficha.getByRole("button", { name: "Ver la cita en su página" }).click();

  const visor = page.getByRole("dialog");
  await expect(visor).toBeVisible();
  await expect(visor).toContainText("PCAP.pdf · página 3 de 12");
  await expect(visor.locator("mark")).toHaveText(CITA);
});
