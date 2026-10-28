import type { Page, Response } from "@playwright/test";
import { test, expect } from "./cuenta-desechable";
import { SEED_LICITACION } from "./fixtures";
import { seleccionarFilaDelRadar } from "./radar-fila";

/**
 * Una oportunidad, del Radar a la oferta en preparación, por la consola.
 *
 * Los tests de escenario de la API ya recorren el embudo entero; lo que no
 * veía nadie es que la **pantalla** deje hacerlo: que el botón de la fila cree
 * la oportunidad, que la ficha ofrezca el único paso posible en cada fase, que
 * la decisión se pueda escribir donde se toma y que la tarea apuntada en la
 * Agenda siga hecha al volver.
 *
 * Con cuenta desechable: abrir una oportunidad le cambia el tablero, la Agenda
 * y la campana a toda la organización de quien la abre.
 */

// A 1440 px el inspector de la Agenda está en pantalla seguro: aparece en
// `xl` (1280 px), que es justo el ancho por defecto del proyecto, y con el
// ancho clavado en el umbral basta un cambio de un píxel para quedarse sin él.
test.use({ viewport: { width: 1440, height: 900 } });

const TITULO = SEED_LICITACION.tituloRadar;
const MOTIVO = "Encaja con la práctica de ERP y el plazo da para preparar la oferta.";
const MOTIVO_ENCAJE = "Es la línea de negocio principal del equipo.";
const TAREA = "Pedir el certificado de solvencia técnica";

test("una oportunidad va del Radar a la oferta en preparación, abriendo en su checklist, con su decisión y su tarea", async ({ page }) => {
  // CU-05 CU-06 CU-07
  //
  // El presupuesto por defecto (30 s) se queda corto para un runner lento:
  // son cuatro pantallas y siete escrituras contra Postgres, cada una con su
  // relectura.
  test.setTimeout(120_000);

  // ── Del expediente a la oportunidad ──────────────────────────────────────
  await page.goto("/radar");
  const fila = await seleccionarFilaDelRadar(page, TITULO);
  const alta = await escritura(page, "POST", /\/api\/v1\/pursuits(\?|$)/, () =>
    fila.getByRole("button", { name: "Abrir", exact: true }).click(),
  );
  expect(alta.status(), "POST /pursuits").toBe(201);

  // Abrirla lleva a su ficha, que nace en la primera fase.
  await page.waitForURL(/\/oportunidades\/\d+$/);
  const rutaFicha = new URL(page.url()).pathname;
  await expect(page.getByRole("heading", { level: 1, name: TITULO })).toBeVisible();
  await esperarFase(page, "Identificada");

  // ── La ficha abre en el checklist (D54) ──────────────────────────────────
  // Lo primero es qué pide el pliego frente a la capacidad de la
  // organización; la decisión va debajo y la matriz ponderada, plegada.
  const checklist = page.getByRole("region", { name: "Checklist go/no-go" });
  await expect(checklist).toBeVisible();
  const decisionDebajo = await checklist.evaluate((nodo) => {
    const decision = document.getElementById("ficha-decision");
    return decision != null && Boolean(nodo.compareDocumentPosition(decision) & Node.DOCUMENT_POSITION_FOLLOWING);
  });
  expect(decisionDebajo, "la decisión va después del checklist").toBe(true);
  await expect(page.getByRole("button", { name: /^Matriz ponderada/ })).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("region", { name: "Matriz go/no-go" })).toHaveCount(0);

  // ── Está en el tablero, en su columna ────────────────────────────────────
  await page.getByRole("link", { name: "Cerrar la ficha" }).click();
  await page.waitForURL(/\/oportunidades$/);
  const columna = page.getByRole("region", { name: "Identificada", exact: true });
  await columna.getByRole("link", { name: TITULO }).click();
  await page.waitForURL((url) => url.pathname === rutaFicha);

  // ── El embudo, paso a paso ───────────────────────────────────────────────
  await avanzar(page, "Empezar a cualificar", "En cualificación");
  await avanzar(page, "Llevar a decisión", "Decisión");

  // Sin GO no hay oferta: el paso existe, pero no se ofrece.
  const empezarOferta = page.getByRole("button", { name: "Empezar la oferta" });
  await expect(empezarOferta).toBeDisabled();
  await expect(page.getByText("Preparar o presentar una oferta exige la decisión GO.")).toBeVisible();

  // ── La matriz go/no-go: un criterio puntuado, con su motivo ──────────────
  // Va plegada y es opcional: se abre a mano. Sin nada puntuado no hay
  // recomendación; con un criterio en 4 la hay, y es provisional porque se
  // calculó sobre uno de cinco.
  await page.getByRole("button", { name: /^Matriz ponderada/ }).click();
  const matriz = page.getByRole("region", { name: "Matriz go/no-go" });
  await expect(matriz.getByText("Sin criterios puntuados")).toBeVisible();
  await matriz
    .getByRole("group", { name: "Puntuación de «Encaje estratégico»" })
    .getByRole("button", { name: "4", exact: true })
    .click();
  await matriz.getByLabel("Motivo de «Encaje estratégico»").fill(MOTIVO_ENCAJE);
  const puntuada = await escritura(page, "PUT", /\/api\/v1\/pursuits\/\d+\/go-no-go/, () =>
    matriz.getByRole("button", { name: "Guardar «Encaje estratégico»" }).click(),
  );
  expect(puntuada.status(), "PUT de la puntuación").toBe(200);
  expect(JSON.parse(puntuada.request().postData() ?? "{}")).toMatchObject({
    criterio: "encaje",
    puntuacion: 4,
    motivo: MOTIVO_ENCAJE,
  });
  await expect(matriz.getByText("Recomienda GO")).toBeVisible();
  await expect(matriz.getByText("1 de 5 puntuados")).toBeVisible();
  await expect(matriz.getByText(/Provisional: calculada solo sobre 1 de 5 criterios/)).toBeVisible();

  // ── La decisión, con su motivo ───────────────────────────────────────────
  const decision = page.getByRole("region", { name: "Decisión del comité" });
  await decision.getByRole("button", { name: "GO", exact: true }).click();
  // El GO sin motivo tampoco se guarda.
  const guardarDecision = decision.getByRole("button", { name: "Guardar decisión" });
  await expect(guardarDecision).toBeDisabled();
  await decision.getByLabel("Motivo de la decisión").fill(MOTIVO);
  const decidida = await escritura(page, "PATCH", rutaApi(rutaFicha), () => guardarDecision.click());
  expect(decidida.status(), "PATCH de la decisión").toBe(200);
  expect(JSON.parse(decidida.request().postData() ?? "{}")).toMatchObject({
    decision: "go",
    decision_reason: MOTIVO,
  });

  await expect(empezarOferta).toBeEnabled();
  await avanzar(page, "Empezar la oferta", "Preparando oferta");

  // ── Una tarea para preparar la oferta, en la Agenda ──────────────────────
  await page.goto("/mi-pipeline");
  const detalle = await abrirEnAgenda(page);
  await detalle.getByRole("textbox", { name: "Nueva tarea", exact: true }).fill(TAREA);
  const creada = await escritura(page, "POST", /\/api\/v1\/pursuits\/\d+\/tasks/, () =>
    detalle.getByRole("button", { name: "Añadir", exact: true }).click(),
  );
  expect(creada.status(), "POST de la tarea").toBe(201);

  const casilla = detalle.getByRole("checkbox", { name: TAREA });
  await expect(casilla).not.toBeChecked();
  const cerrada = await escritura(page, "PATCH", /\/api\/v1\/pursuits\/\d+\/tasks\/\d+/, () => casilla.click());
  expect(cerrada.status(), "PATCH de la tarea").toBe(200);
  await expect(casilla).toBeChecked();

  // ── Todo sigue ahí tras recargar ─────────────────────────────────────────
  await page.reload();
  const detalleTrasRecarga = await abrirEnAgenda(page);
  await expect(detalleTrasRecarga.getByRole("checkbox", { name: TAREA })).toBeChecked();

  await page.goto(rutaFicha);
  await esperarFase(page, "Preparando oferta");
  const decisionGuardada = page.getByRole("region", { name: "Decisión del comité" });
  await expect(decisionGuardada.getByText(MOTIVO)).toBeVisible();
  await expect(decisionGuardada.getByText(/^GO\b/)).toBeVisible();

  // Y en el tablero cambió de columna: ya no está donde nació.
  await page.goto("/oportunidades");
  await expect(
    page.getByRole("region", { name: "Preparando oferta", exact: true }).getByRole("link", { name: TITULO }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Identificada", exact: true }).getByRole("link", { name: TITULO }),
  ).toHaveCount(0);
});

/** `/oportunidades/7` → la ruta de la API que escribe esa oportunidad. */
function rutaApi(rutaFicha: string): RegExp {
  const id = rutaFicha.split("/").pop();
  return new RegExp(`/api/v1/pursuits/${id}(\\?|$)`);
}

/**
 * Lanza *accion* y devuelve la respuesta de la escritura que provoca.
 *
 * Se espera a la respuesta y no a un aviso en pantalla: el aviso dura unos
 * segundos y dice lo mismo para dos cosas distintas («Decisión guardada»).
 */
async function escritura(
  page: Page,
  metodo: "POST" | "PUT" | "PATCH",
  ruta: RegExp,
  accion: () => Promise<void>,
): Promise<Response> {
  const [respuesta] = await Promise.all([
    page.waitForResponse((candidata) => candidata.request().method() === metodo && ruta.test(candidata.url())),
    accion(),
  ]);
  return respuesta;
}

/** La fase en la que la ficha dice estar: la casilla marcada del path. */
async function esperarFase(page: Page, fase: string): Promise<void> {
  await expect(
    page.getByRole("navigation", { name: "Fase de la oportunidad" }).locator('[aria-current="step"]'),
  ).toHaveText(fase, { timeout: 15_000 });
}

/**
 * Pulsa el único paso que la ficha ofrece y espera a verla en la fase nueva.
 *
 * Esperar a la fase no es cortesía: cada PATCH lleva `expected_version`, y el
 * siguiente botón pulsado antes de que la ficha tenga la versión nueva
 * recibiría un 409 de «alguien del equipo la cambió».
 */
async function avanzar(page: Page, boton: string, fase: string): Promise<void> {
  const movida = await escritura(page, "PATCH", /\/api\/v1\/pursuits\/\d+(\?|$)/, () =>
    page.getByRole("button", { name: boton, exact: true }).click(),
  );
  expect(movida.status(), `PATCH de «${boton}»`).toBe(200);
  await esperarFase(page, fase);
}

/** Selecciona la oportunidad en la Agenda y devuelve su panel de detalle. */
async function abrirEnAgenda(page: Page) {
  // El nombre de la fila empieza por la clase de compromiso y su título; lo
  // que sigue (aviso, fase, fecha) cambia con el calendario.
  const fila = page.getByRole("button", { name: new RegExp(`^Oportunidad: ${TITULO}`) });
  await expect(fila, "la oportunidad no aparece en la Agenda").toBeVisible({ timeout: 20_000 });
  await fila.click();
  const detalle = page.getByRole("complementary", { name: "Detalle del compromiso" });
  await expect(detalle.getByRole("heading", { name: TITULO })).toBeVisible();
  return detalle;
}
