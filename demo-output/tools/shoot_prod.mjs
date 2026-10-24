// Rodaje de la demo en PRODUCCIÓN: recorre la app real con la cuenta de las
// variables TF_DEMO_EMAIL / TF_DEMO_PASSWORD, en la organización personal
// (ORG), y guarda por estado una captura 1920x1080 y la caja del elemento que
// se va a pulsar. Antes de cada captura sustituye en el DOM cualquier correo y
// el nombre de usuario de la cuenta: no sale ningún dato personal.
// Escribe de verdad (oportunidad, tarea, alerta, cuenta): `creados.json` deja
// lo creado para la limpieza (limpiar_prod.mjs).
// Salida: <OUT>/<shot>-<nn>-<nombre>.png, <OUT>/manifest.json, <OUT>/creados.json
import fs from "node:fs";
import { chromium } from "/home/user/TenderFlow/web/node_modules/playwright/index.mjs";

const OUT = process.argv[2];
const SOLO = process.argv[3] ? process.argv[3].split(",") : null;
const BASE = process.env.TF_BASE || "https://tenderflowesp.vercel.app";
const ORG = Number(process.env.TF_ORG || 10);
const DPR = 1.2;
const PATRON = "entorno SAP"; // fila del Radar del expediente protagonista
const LIC = "040-2026-0110";
const ORGANO = "Mutua Universal";
const MOTIVO = "Encaja con nuestra práctica SAP y el plazo da para preparar la oferta.";
const TAREA = "Pedir el certificado de solvencia técnica";
const FRASE = "mantenimiento SAP abiertas en Andalucía";
const PALABRA = "SAP";
const EMAIL = process.env.TF_DEMO_EMAIL;
const LOCAL = EMAIL.split("@")[0];

fs.mkdirSync(OUT, { recursive: true });
const manifest = fs.existsSync(`${OUT}/manifest.json`) ? JSON.parse(fs.readFileSync(`${OUT}/manifest.json`, "utf8")) : {};
const creados = fs.existsSync(`${OUT}/creados.json`) ? JSON.parse(fs.readFileSync(`${OUT}/creados.json`, "utf8")) : {};
const guardarCreados = () => fs.writeFileSync(`${OUT}/creados.json`, JSON.stringify(creados, null, 1));

const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium", proxy: { server: process.env.HTTPS_PROXY } });
async function contexto(conSesion) {
  const ctx = await browser.newContext({
    viewport: { width: 1600, height: 900 }, deviceScaleFactor: DPR, colorScheme: "dark",
    locale: "es-ES", timezoneId: "Europe/Madrid", reducedMotion: "reduce",
  });
  if (conSesion) {
    await ctx.addInitScript((org) => {
      localStorage.setItem("tenderflow-active-organization", JSON.stringify({ state: { activeOrganizationId: org, ultimaPorDefecto: org }, version: 0 }));
    }, ORG);
    const r = await ctx.request.post(`${BASE}/api/v1/auth/login`, { data: { email: EMAIL, password: process.env.TF_DEMO_PASSWORD } });
    if (!r.ok()) throw new Error(`login ${r.status()}`);
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
// Sustituye correos y el nombre de usuario de la cuenta en texto y campos.
async function enmascarar() {
  await page.evaluate((local) => {
    const correo = /[\w.+-]+@[\w-]+(\.[\w-]+)+/g;
    const usuario = new RegExp(local.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    const limpiar = (t) => t.replace(correo, "usuario@empresa.es").replace(usuario, "Usuario demo");
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let nodo = w.nextNode(); nodo; nodo = w.nextNode()) {
      const nuevo = limpiar(nodo.nodeValue);
      if (nuevo !== nodo.nodeValue) nodo.nodeValue = nuevo;
    }
    for (const el of document.querySelectorAll("input, textarea")) {
      if (el.value && limpiar(el.value) !== el.value) el.value = limpiar(el.value);
      const ph = el.getAttribute("placeholder");
      if (ph && limpiar(ph) !== ph) el.setAttribute("placeholder", limpiar(ph));
    }
  }, LOCAL);
}
// Guarda el estado actual. `objetivo` es el locator que se pulsará a continuación.
async function snap(nombre, objetivo = null, espera = 900) {
  await page.waitForTimeout(espera);
  await page.mouse.move(1599, 899);
  await enmascarar();
  const file = `${shot}-${String(n++).padStart(2, "0")}-${nombre}.png`;
  const target = objetivo ? await caja(objetivo) : null;
  await page.screenshot({ path: `${OUT}/${file}` });
  const html = await page.content();
  if (html.includes(EMAIL) || html.toLowerCase().includes(LOCAL.toLowerCase())) console.log("   aviso: queda el usuario en atributos del DOM (no visible)");
  manifest[shot].push({ file, nombre, target, url: page.url().replace(BASE, "") });
  console.log("  ", file, target ? JSON.stringify(target) : "");
}
async function teclear(loc, texto, prefijo, paso = 4) {
  await loc.click();
  let escrito = "";
  for (let i = 0; i < texto.length; i += paso) {
    const trozo = texto.slice(i, i + paso);
    await loc.pressSequentially(trozo, { delay: 5 });
    escrito += trozo;
    await snap(`${prefijo}-t${String(escrito.length).padStart(3, "0")}`, null, 80);
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
    await enmascarar().catch(() => {});
    await page.screenshot({ path: `${OUT}/ERROR-${nombre}.png` });
  }
  fs.writeFileSync(`${OUT}/manifest.json`, JSON.stringify(manifest, null, 1));
}
async function ir(ruta, espera = 2000) {
  await page.goto(BASE + ruta, { waitUntil: "networkidle", timeout: 90000 }).catch(() => console.log("   (networkidle no llegó)", ruta));
  await page.waitForTimeout(espera);
  const aviso = page.getByRole("button", { name: "Entendido, no volver a mostrar" });
  if (await aviso.isVisible().catch(() => false)) {
    await aviso.click();
    await page.waitForTimeout(300);
  }
}
const fase = (nombre) => page.getByRole("navigation", { name: "Fase de la oportunidad" }).locator('[aria-current="step"]').filter({ hasText: nombre }).waitFor({ timeout: 30000 });
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// ---------- Superficie pública (sin sesión) ----------
const anon = await contexto(false);
page = await anon.newPage();
await escena("publico", async () => {
  await ir("/");
  await snap("landing");
  await ir("/licitaciones");
  const hub = page.locator('main a[href^="/licitaciones/"]').filter({ hasText: "Madrid" }).first();
  await snap("indice", hub);
  await hub.click();
  await page.waitForLoadState("networkidle").catch(() => {});
  const ficha = page.locator('main a[href^="/licitacion"]').first();
  await snap("hub", ficha, 1500);
  await ficha.click();
  await page.waitForLoadState("networkidle").catch(() => {});
  await snap("ficha", null, 1500);
});
await anon.close();

// ---------- Cuenta, organización personal ----------
const ctx = await contexto(true);
page = await ctx.newPage();
let TITULO = null;

await escena("radar", async () => {
  await ir("/radar", 3000);
  const fila = page.locator("[data-active]").filter({ hasText: PATRON }).first();
  await fila.waitFor({ timeout: 60000 });
  const sel = fila.getByRole("button", { name: /^Seleccionar / });
  TITULO = (await sel.getAttribute("aria-label")).replace(/^Seleccionar /, "");
  creados.titulo = TITULO;
  await snap("bandeja", sel, 1200);
  await sel.click();
  const abrir = page.getByRole("button", { name: "Abrir oportunidad" });
  await snap("inspector", abrir, 2000);
  await abrir.click();
  await page.waitForURL(/\/oportunidades\/\d+$/, { timeout: 60000 });
  creados.pursuit = page.url().replace(BASE, "");
  guardarCreados();
  await page.waitForLoadState("networkidle").catch(() => {});
  await snap("pursuit-identificada", page.getByRole("button", { name: "Empezar a cualificar", exact: true }), 2000);
});

await escena("pursuit", async () => {
  if (!/\/oportunidades\/\d+$/.test(page.url())) await ir(creados.pursuit);
  await page.getByRole("button", { name: "Empezar a cualificar", exact: true }).click();
  await fase("En cualificación");
  await snap("cualificacion", page.getByRole("button", { name: "Llevar a decisión", exact: true }), 1500);
  await page.getByRole("button", { name: "Llevar a decisión", exact: true }).click();
  await fase("Decisión");
  await page.waitForTimeout(1200);
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
  await page.waitForLoadState("networkidle").catch(() => {});
  const empezar = page.getByRole("button", { name: "Empezar la oferta" });
  await snap("decidida", empezar, 1500);
  await empezar.click();
  await fase("Preparando oferta");
  await page.evaluate(() => window.scrollTo(0, 0));
  const precio = page.getByRole("tab", { name: "Precio" }).or(page.getByRole("link", { name: "Precio", exact: true })).or(page.getByRole("button", { name: "Precio", exact: true })).first();
  await snap("preparando", precio, 1500);
  await precio.click();
  await page.waitForLoadState("networkidle").catch(() => {});
  await snap("precio", null, 3500);
  await page.mouse.wheel(0, 500);
  await snap("precio-2", null, 1200);
});

await escena("tablero", async () => {
  await ir("/oportunidades", 3000);
  await snap("kanban", null, 1500);
});

await escena("agenda", async () => {
  await ir("/mi-pipeline", 3000);
  const fila = page.getByRole("button", { name: new RegExp(`^Oportunidad: ${esc(TITULO ?? creados.titulo)}`) });
  await fila.waitFor({ timeout: 60000 });
  await snap("agenda", fila, 1200);
  await fila.click();
  const detalle = page.getByRole("complementary", { name: "Detalle del compromiso" });
  const caja2 = detalle.getByRole("textbox", { name: "Nueva tarea", exact: true });
  await snap("detalle", caja2, 1200);
  await teclear(caja2, TAREA, "tarea", 8);
  const anadir = detalle.getByRole("button", { name: "Añadir", exact: true });
  await snap("tarea-escrita", anadir);
  await anadir.click();
  await page.waitForLoadState("networkidle").catch(() => {});
  const casilla = detalle.getByRole("checkbox", { name: TAREA });
  await casilla.waitFor({ timeout: 30000 });
  await snap("tarea-creada", casilla);
  await casilla.click();
  await page.waitForLoadState("networkidle").catch(() => {});
  await snap("tarea-hecha", null, 1500);
});

await escena("detalle", async () => {
  await ir(`/detalle?lic=${LIC}`, 3500);
  const tab = page.getByRole("tab", { name: "Competencia" }).or(page.getByRole("button", { name: "Competencia", exact: true })).first();
  await snap("ficha", tab, 1500);
  await tab.click();
  await snap("ficha-competencia", null, 3000);
});

await escena("investigador", async () => {
  await ir("/investigador");
  const form = page.getByRole("search");
  const campo = form.getByRole("textbox", { name: "Busca o pregunta" });
  await snap("vacio", campo);
  await teclear(campo, FRASE, "frase", 6);
  const buscar = form.getByRole("button", { name: "Buscar", exact: true });
  await snap("frase-escrita", buscar);
  await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/v1/search/semantic"), { timeout: 90000 }),
    buscar.click(),
  ]);
  await snap("resultados", null, 2500);
});

await escena("watchlist", async () => {
  await ir("/mi-watchlist");
  const campo = page.getByRole("textbox", { name: "Palabra clave *" });
  await snap("vacia", campo, 900);
  await teclear(campo, PALABRA, "palabra", 1);
  const ver = page.getByRole("button", { name: "Ver cuántas alertas daría" });
  await snap("palabra-escrita", ver);
  await ver.click();
  await page.waitForLoadState("networkidle").catch(() => {});
  const anadir = page.getByRole("button", { name: "Añadir regla" });
  await snap("vista-previa", anadir, 2500);
  const [alta] = await Promise.all([
    page.waitForResponse((r) => /\/api\/v1\/watchlist\/rules(\?|$)/.test(r.url()) && r.request().method() === "POST", { timeout: 60000 }),
    anadir.click(),
  ]);
  try { creados.regla = (await alta.json()).id; } catch { creados.regla = "?"; }
  guardarCreados();
  await page.waitForLoadState("networkidle").catch(() => {});
  await snap("regla-creada", null, 2500);
  await page.getByRole("heading", { name: "Resultados combinados" }).evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => {});
  await snap("resultados-regla", null, 1500);
});

await escena("competencia", async () => {
  await ir("/competencia", 4000);
  const ranking = page.getByRole("table", { name: /^Ranking de competidores/ });
  await ranking.waitFor({ timeout: 60000 });
  await snap("panorama", null, 1500);
  const segunda = ranking.locator("tbody tr").nth(1).getByRole("button").first();
  const nombre = (await segunda.innerText()).trim();
  await segunda.scrollIntoViewIfNeeded();
  await snap("ranking", segunda, 800);
  await segunda.click();
  const perfil = page.getByRole("region", { name: `Perfil de ${nombre}` });
  await perfil.waitFor({ timeout: 60000 });
  await perfil.evaluate((el) => el.scrollIntoView({ block: "start" }));
  await snap("perfil", null, 3000);
});

await escena("mercado", async () => {
  await ir("/mercado", 4000);
  await snap("tiempo", null, 2000);
  for (const vista of ["Geografía", "CPV", "Órganos"]) {
    const t = page.getByRole("tab", { name: vista, exact: true }).or(page.getByRole("button", { name: vista, exact: true })).or(page.getByRole("link", { name: vista, exact: true })).first();
    if (!(await t.isVisible().catch(() => false))) continue;
    await t.click();
    await page.waitForLoadState("networkidle").catch(() => {});
    await snap(vista.toLowerCase().normalize("NFD").replace(/[^a-z]/g, ""), null, vista === "Geografía" ? 8000 : 3500);
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
  await teclear(combo, ORGANO, "organo", 5);
  const opcion = dialogo.getByRole("listbox", { name: "Órganos que coinciden" }).getByRole("option", { name: new RegExp(`^${esc(ORGANO)}`) }).first();
  await opcion.waitFor({ timeout: 30000 });
  await snap("opciones", opcion, 1200);
  await opcion.click();
  const crear = dialogo.getByRole("button", { name: "Crear cuenta" });
  await snap("elegido", crear);
  await crear.click();
  await dialogo.waitFor({ state: "hidden", timeout: 30000 });
  const enlace = page.getByRole("main").getByRole("link", { name: new RegExp(`^${esc(ORGANO)}`) }).first();
  await enlace.waitFor({ timeout: 30000 });
  await snap("lista", enlace, 1200);
  await enlace.click();
  await page.waitForURL(/\/cuentas\/\d+$/, { timeout: 60000 });
  creados.cuenta = page.url().replace(BASE, "");
  guardarCreados();
  await page.waitForLoadState("networkidle").catch(() => {});
  await snap("ficha", null, 3000);
});

await escena("paleta", async () => {
  await ir("/resumen");
  await page.keyboard.press("Control+k");
  await page.waitForTimeout(500);
  await snap("abierta", null, 300);
  await page.keyboard.type("compet", { delay: 20 });
  await snap("buscando", null, 800);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Notificaciones" }).click();
  await snap("campana", null, 1500);
  await page.keyboard.press("Escape");
});

await escena("resumen1", async () => {
  await ir("/resumen", 3500);
  await snap("resumen", null, 1500);
});

await escena("equipo", async () => {
  await ir("/equipo");
  await snap("equipo", null, 1500);
  await ir("/ajustes");
  for (const [nombre, etiqueta] of [["seguridad", "Seguridad"], ["claves", "Claves de API"]]) {
    const t = page.getByRole("tab", { name: etiqueta }).or(page.getByRole("button", { name: etiqueta, exact: true })).first();
    if (await t.isVisible().catch(() => false)) {
      await t.click();
      await snap(nombre, null, 1200);
    }
  }
});

await escena("ops", async () => {
  await ir("/ops", 3000);
  for (const vista of ["Ejecuciones", "Datos"]) {
    const t = page.getByRole("tab", { name: vista, exact: true }).or(page.getByRole("button", { name: vista, exact: true })).or(page.getByRole("link", { name: vista, exact: true })).first();
    if (!(await t.isVisible().catch(() => false))) continue;
    await t.click();
    await page.waitForLoadState("networkidle").catch(() => {});
    await snap(vista.toLowerCase(), null, 3000);
  }
});
await browser.close();
console.log("hecho", JSON.stringify(creados));
