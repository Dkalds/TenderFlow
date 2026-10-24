// Rodaje de la demo: recorre la app real (datos del seed) y guarda, para cada
// estado, una captura 1920x1080 y la caja del elemento que se va a pulsar.
// Salida: <OUT>/<shot>-<nn>-<nombre>.png y <OUT>/manifest.json
import fs from "node:fs";
import { chromium } from "/home/user/TenderFlow/web/node_modules/playwright/index.mjs";

const OUT = process.argv[2];
const SOLO = process.argv[3] ? process.argv[3].split(",") : null;
const BASE = "http://localhost:3000";
const DPR = 1.2;
const TITULO = "Implantación de sistema ERP para gestión municipal";
const ORGANO = "Ministerio de Hacienda";
const MOTIVO = "Encaja con la práctica de ERP y el plazo da para preparar la oferta.";
const TAREA = "Pedir el certificado de solvencia técnica";
const FRASE = "auditoria de sistemas del Ayuntamiento de Madrid";

fs.mkdirSync(OUT, { recursive: true });
const manifest = fs.existsSync(`${OUT}/manifest.json`) ? JSON.parse(fs.readFileSync(`${OUT}/manifest.json`, "utf8")) : {};

const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });
async function contexto(email, pw) {
  const ctx = await browser.newContext({
    viewport: { width: 1600, height: 900 }, deviceScaleFactor: DPR, colorScheme: "dark",
    locale: "es-ES", timezoneId: "Europe/Madrid", reducedMotion: "reduce",
  });
  if (email) {
    const r = await ctx.request.post(`${BASE}/api/v1/auth/login`, { data: { email, password: pw } });
    if (!r.ok()) throw new Error(`login ${email} ${r.status()}`);
  }
  return ctx;
}

let page;
let shot;
let n;
async function caja(loc) {
  const b = await loc.boundingBox();
  if (!b) return null;
  return { x: Math.round(b.x * DPR), y: Math.round(b.y * DPR), w: Math.round(b.width * DPR), h: Math.round(b.height * DPR) };
}
// Guarda el estado actual. `objetivo` es el locator que se pulsará a continuación.
async function snap(nombre, objetivo = null, espera = 700) {
  await page.waitForTimeout(espera);
  await page.mouse.move(1599, 899);
  const file = `${shot}-${String(n++).padStart(2, "0")}-${nombre}.png`;
  const target = objetivo ? await caja(objetivo) : null;
  await page.screenshot({ path: `${OUT}/${file}` });
  manifest[shot].push({ file, nombre, target, url: page.url() });
  console.log("  ", file, target ? JSON.stringify(target) : "");
}
async function teclear(loc, texto, prefijo, paso = 4) {
  await loc.click();
  let escrito = "";
  for (let i = 0; i < texto.length; i += paso) {
    const trozo = texto.slice(i, i + paso);
    await loc.pressSequentially(trozo, { delay: 5 });
    escrito += trozo;
    await snap(`${prefijo}-t${String(escrito.length).padStart(3, "0")}`, null, 60);
  }
}
async function escena(nombre, fn) {
  if (SOLO && !SOLO.includes(nombre)) return;
  shot = nombre;
  n = 0;
  manifest[shot] = [];
  console.log("==", nombre);
  try {
    await fn();
  } catch (e) {
    console.log("!! fallo en", nombre, e.message.split("\n")[0]);
    await page.screenshot({ path: `${OUT}/ERROR-${nombre}.png` });
  }
  fs.writeFileSync(`${OUT}/manifest.json`, JSON.stringify(manifest, null, 1));
}
async function ir(ruta) {
  await page.goto(BASE + ruta, { waitUntil: "networkidle", timeout: 40000 });
  const aviso = page.getByRole("button", { name: "Entendido, no volver a mostrar" });
  if (await aviso.isVisible().catch(() => false)) {
    await aviso.click();
    await page.waitForTimeout(300);
  }
}

// ---------- Superficie pública (sin sesión) ----------
const anon = await contexto(null);
page = await anon.newPage();
await escena("publico", async () => {
  await ir("/");
  await snap("landing");
  await ir("/licitaciones");
  const hub = page.locator('main a[href^="/licitaciones/"]').first();
  await snap("indice", hub);
  await hub.click();
  await page.waitForLoadState("networkidle");
  const ficha = page.locator('main a[href^="/licitacion"]').first();
  await snap("hub", ficha);
  await ficha.click();
  await page.waitForLoadState("networkidle");
  await snap("ficha");
});
await anon.close();

// ---------- Usuario demo ----------
const demo = await contexto("demo@tenderflow.dev", process.env.DEMO_PW);
page = await demo.newPage();

await escena("resumen0", async () => {
  await ir("/resumen");
  await snap("resumen");
});

await escena("radar", async () => {
  await ir("/radar");
  const fila = page.locator("[data-active]").filter({ hasText: TITULO });
  const sel = fila.getByRole("button", { name: `Seleccionar ${TITULO}` });
  await snap("bandeja", sel, 1200);
  await sel.click();
  const abrir = page.getByRole("button", { name: "Abrir oportunidad" });
  await snap("inspector", abrir);
  await abrir.click();
  await page.waitForURL(/\/oportunidades\/\d+$/);
  await page.waitForLoadState("networkidle");
  await snap("pursuit-identificada", page.getByRole("button", { name: "Empezar a cualificar", exact: true }), 900);
});

await escena("pursuit", async () => {
  if (!/\/oportunidades\/\d+$/.test(page.url())) await ir("/oportunidades/1");
  await page.getByRole("button", { name: "Empezar a cualificar", exact: true }).click();
  await page.waitForLoadState("networkidle");
  await snap("cualificacion", page.getByRole("button", { name: "Llevar a decisión", exact: true }));
  await page.getByRole("button", { name: "Llevar a decisión", exact: true }).click();
  await page.getByRole("navigation", { name: "Fase de la oportunidad" }).locator('[aria-current="step"]').filter({ hasText: "Decisión" }).waitFor({ timeout: 15000 });
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(800);
  const decision = page.getByRole("region", { name: "Decisión del comité" });
  await decision.waitFor();
  await decision.evaluate((el) => el.scrollIntoView({ block: "center" }));
  const go = decision.getByRole("button", { name: "GO", exact: true });
  await snap("decision", go);
  await go.click();
  const motivo = decision.getByLabel("Motivo de la decisión");
  await snap("go-elegido", motivo);
  await teclear(motivo, MOTIVO, "motivo", 9);
  const guardar = decision.getByRole("button", { name: "Guardar decisión" });
  await snap("motivo-escrito", guardar);
  await guardar.click();
  await page.waitForLoadState("networkidle");
  const empezar = page.getByRole("button", { name: "Empezar la oferta" });
  await snap("decidida", empezar);
  await empezar.click();
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => window.scrollTo(0, 0));
  const precio = page.getByRole("tab", { name: "Precio" }).or(page.getByRole("link", { name: "Precio", exact: true })).or(page.getByRole("button", { name: "Precio", exact: true })).first();
  await snap("preparando", precio);
  await precio.click();
  await page.waitForLoadState("networkidle");
  await snap("precio", null, 1500);
  await page.mouse.wheel(0, 500);
  await snap("precio-2", null, 800);
});

await escena("tablero", async () => {
  await ir("/oportunidades");
  await snap("kanban", null, 1200);
});

await escena("agenda", async () => {
  await ir("/mi-pipeline");
  const fila = page.getByRole("button", { name: new RegExp(`^Oportunidad: ${TITULO}`) });
  await fila.waitFor({ timeout: 20000 });
  await snap("agenda", fila, 900);
  await fila.click();
  const detalle = page.getByRole("complementary", { name: "Detalle del compromiso" });
  const caja2 = detalle.getByRole("textbox", { name: "Nueva tarea", exact: true });
  await snap("detalle", caja2);
  await teclear(caja2, TAREA, "tarea", 8);
  const anadir = detalle.getByRole("button", { name: "Añadir", exact: true });
  await snap("tarea-escrita", anadir);
  await anadir.click();
  await page.waitForLoadState("networkidle");
  const casilla = detalle.getByRole("checkbox", { name: TAREA });
  await snap("tarea-creada", casilla);
  await casilla.click();
  await page.waitForLoadState("networkidle");
  await snap("tarea-hecha");
});

await escena("detalle", async () => {
  await ir("/detalle?lic=SEED-2026-008");
  const tab = page.getByRole("tab", { name: "Competencia" }).or(page.getByRole("button", { name: "Competencia", exact: true })).first();
  await snap("ficha", tab, 1200);
  await tab.click();
  await snap("ficha-competencia", null, 1200);
});

await escena("investigador", async () => {
  await ir("/investigador");
  const form = page.getByRole("search");
  const campo = form.getByRole("textbox", { name: "Busca o pregunta" });
  await snap("vacio", campo);
  await teclear(campo, FRASE, "frase", 6);
  const buscar = form.getByRole("button", { name: "Buscar", exact: true });
  await snap("frase-escrita", buscar);
  await buscar.click();
  await page.waitForResponse((r) => r.url().includes("/api/v1/search/semantic"));
  const alerta = page.getByRole("link", { name: "Crear alerta" });
  await snap("resultados", alerta, 1200);
});

await escena("watchlist", async () => {
  await ir("/mi-watchlist");
  const campo = page.getByRole("textbox", { name: "Palabra clave *" });
  await snap("vacia", campo, 900);
  await teclear(campo, "ERP", "palabra", 1);
  const ver = page.getByRole("button", { name: "Ver cuántas alertas daría" });
  await snap("palabra-escrita", ver);
  await ver.click();
  await page.waitForLoadState("networkidle");
  const anadir = page.getByRole("button", { name: "Añadir regla" });
  await snap("vista-previa", anadir, 900);
  await anadir.click();
  await page.waitForLoadState("networkidle");
  await snap("regla-creada", null, 1200);
  await page.getByRole("heading", { name: "Resultados combinados" }).evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => {});
  await snap("resultados-regla", null, 800);
});

await escena("competencia", async () => {
  await ir("/competencia");
  const ranking = page.getByRole("table", { name: /^Ranking de competidores/ });
  await ranking.waitFor({ timeout: 20000 });
  const segunda = ranking.getByRole("button", { name: "SecureTech Solutions S.L.", exact: true });
  await snap("panorama", null, 1200);
  await segunda.scrollIntoViewIfNeeded();
  await snap("ranking", segunda, 600);
  await segunda.click();
  const perfil = page.getByRole("region", { name: "Perfil de SecureTech Solutions S.L." });
  await perfil.waitFor();
  await perfil.evaluate((el) => el.scrollIntoView({ block: "start" }));
  await snap("perfil", null, 1200);
});

await escena("mercado", async () => {
  await ir("/mercado");
  await snap("tiempo", null, 1500);
  for (const vista of ["Geografía", "CPV", "Órganos"]) {
    const t = page.getByRole("tab", { name: vista, exact: true }).or(page.getByRole("button", { name: vista, exact: true })).or(page.getByRole("link", { name: vista, exact: true })).first();
    if (!(await t.isVisible().catch(() => false))) continue;
    await t.click();
    await page.waitForLoadState("networkidle");
    await snap(vista.toLowerCase().normalize("NFD").replace(/[^a-z]/g, ""), null, 1500);
  }
});

await escena("cuentas", async () => {
  await ir("/cuentas");
  const nueva = page.getByRole("button", { name: "Nueva cuenta" }).first();
  await snap("vacio", nueva, 900);
  await nueva.click();
  const dialogo = page.getByRole("dialog", { name: "Nueva cuenta" });
  const combo = dialogo.getByRole("combobox", { name: "Órganos de contratación" });
  await snap("dialogo", combo);
  await teclear(combo, ORGANO, "organo", 6);
  const opcion = dialogo.getByRole("listbox", { name: "Órganos que coinciden" }).getByRole("option", { name: new RegExp(`^${ORGANO}`) });
  await opcion.waitFor();
  await snap("opciones", opcion);
  await opcion.click();
  const crear = dialogo.getByRole("button", { name: "Crear cuenta" });
  await snap("elegido", crear);
  await crear.click();
  await dialogo.waitFor({ state: "hidden" });
  const enlace = page.getByRole("link", { name: ORGANO, exact: true });
  await snap("lista", enlace, 900);
  await enlace.click();
  await page.waitForURL(/\/cuentas\/\d+$/);
  await page.waitForLoadState("networkidle");
  await snap("ficha", null, 1200);
});

await escena("direccion", async () => {
  await ir("/direccion");
  await snap("direccion", null, 1500);
});

await escena("paleta", async () => {
  await ir("/resumen");
  await page.keyboard.press("Control+k");
  await page.waitForTimeout(400);
  await snap("abierta", null, 300);
  await page.keyboard.type("compet", { delay: 20 });
  await snap("buscando", null, 500);
  await page.keyboard.press("Escape");
  const campana = page.getByRole("button", { name: "Notificaciones" });
  await campana.click();
  await snap("campana", null, 900);
  await page.keyboard.press("Escape");
});

await escena("resumen1", async () => {
  await ir("/resumen");
  await snap("resumen", null, 1500);
});

await escena("equipo", async () => {
  await ir("/equipo");
  await snap("equipo", null, 1200);
  await ir("/ajustes");
  const seg = page.getByRole("tab", { name: "Seguridad" }).or(page.getByRole("button", { name: "Seguridad", exact: true })).first();
  if (await seg.isVisible().catch(() => false)) {
    await seg.click();
    await snap("seguridad", null, 1000);
  }
  const claves = page.getByRole("tab", { name: "Claves de API" }).or(page.getByRole("button", { name: "Claves de API", exact: true })).first();
  if (await claves.isVisible().catch(() => false)) {
    await claves.click();
    await snap("claves", null, 1000);
  }
});
await demo.close();

// ---------- Admin ----------
const admin = await contexto("admin@tenderflow.dev", process.env.ADMIN_PW);
page = await admin.newPage();
await escena("ops", async () => {
  await ir("/ops");
  await snap("estado", null, 1500);
  for (const vista of ["Ejecuciones", "Datos"]) {
    const t = page.getByRole("tab", { name: vista, exact: true }).or(page.getByRole("button", { name: vista, exact: true })).or(page.getByRole("link", { name: vista, exact: true })).first();
    if (!(await t.isVisible().catch(() => false))) continue;
    await t.click();
    await page.waitForLoadState("networkidle");
    await snap(vista.toLowerCase(), null, 1500);
  }
});
await browser.close();
console.log("hecho");
