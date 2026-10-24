// Limpieza de lo creado por shoot_prod.mjs en la organización personal.
// Lee <creados.json>: borra las tareas de la oportunidad, la retira desde su
// ficha (no hay DELETE de oportunidades), borra la regla y la cuenta, y verifica.
import fs from "node:fs";
import { chromium } from "/home/user/TenderFlow/web/node_modules/playwright/index.mjs";

const BASE = "https://tenderflowesp.vercel.app";
const ORG = 10;
const creados = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const pursuitId = Number(creados.pursuit.split("/").pop());
const cuentaId = Number(creados.cuenta.split("/").pop());
const q = `organization_id=${ORG}`;

const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium", proxy: { server: process.env.HTTPS_PROXY } });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, colorScheme: "dark", locale: "es-ES" });
await ctx.addInitScript((org) => localStorage.setItem("tenderflow-active-organization", JSON.stringify({ state: { activeOrganizationId: org, ultimaPorDefecto: org }, version: 0 })), ORG);
await ctx.request.post(`${BASE}/api/v1/auth/login`, { data: { email: process.env.TF_DEMO_EMAIL, password: process.env.TF_DEMO_PASSWORD } });
const api = ctx.request;
// Las escrituras llevan el token CSRF de la cookie, como el cliente web.
const csrf = (await ctx.cookies()).find((c) => /csrf/i.test(c.name));
const H = csrf ? { "X-CSRF-Token": csrf.value } : {};

// 1. Tareas de la oportunidad
const tareas = await (await api.get(`${BASE}/api/v1/pursuits/${pursuitId}/tasks?${q}`)).json();
const lista = Array.isArray(tareas) ? tareas : tareas.items ?? [];
for (const t of lista) {
  const r = await api.delete(`${BASE}/api/v1/pursuits/${pursuitId}/tasks/${t.id}?${q}`, { headers: H });
  console.log("tarea", t.id, "DELETE", r.status());
}

// 2. Retirar la oportunidad desde su ficha
const page = await ctx.newPage();
await page.goto(`${BASE}/oportunidades/${pursuitId}`, { waitUntil: "networkidle", timeout: 90000 });
await page.waitForTimeout(2000);
await page.getByRole("button", { name: /^Retirar/ }).first().click();
const dialogo = page.getByRole("dialog");
await dialogo.waitFor({ timeout: 15000 });
await dialogo.getByRole("combobox", { name: "Motivo del cierre" }).click();
const opciones = page.getByRole("option");
const textos = await opciones.allInnerTexts();
console.log("motivos:", textos.join(" · "));
const idx = Math.max(0, textos.findIndex((t) => /otro|sin motivo|no aplica/i.test(t)));
await opciones.nth(idx).click();
console.log("motivo elegido:", textos[idx]);
await Promise.all([
  page.waitForResponse((r) => r.url().includes(`/api/v1/pursuits/${pursuitId}`) && r.request().method() === "PATCH", { timeout: 30000 }),
  dialogo.getByRole("button", { name: "Retirar", exact: true }).click(),
]);
await page.waitForTimeout(2000);
const p = await (await api.get(`${BASE}/api/v1/pursuits/${pursuitId}?${q}`)).json();
console.log("oportunidad", pursuitId, "estado:", p.status, "resultado:", p.outcome ?? p.resultado ?? "");

// 3. Regla de alerta
const rr = await api.delete(`${BASE}/api/v1/watchlist/rules/${creados.regla}?${q}`, { headers: H });
console.log("regla", creados.regla, "DELETE", rr.status());

// 4. Cuenta
const rc = await api.delete(`${BASE}/api/v1/cuentas/${cuentaId}?${q}`, { headers: H });
console.log("cuenta", cuentaId, "DELETE", rc.status());

// Verificación
const reglas = await (await api.get(`${BASE}/api/v1/watchlist/rules?${q}`)).json();
const cuentas = await (await api.get(`${BASE}/api/v1/cuentas?${q}`)).json();
const pur = await (await api.get(`${BASE}/api/v1/pursuits?${q}`)).json();
const abiertas = (pur.items ?? pur).filter((x) => !["closed", "cerrada", "withdrawn", "retirada", "won", "lost"].includes(String(x.status).toLowerCase()));
console.log("quedan reglas:", (reglas.items ?? reglas).length, "cuentas:", (cuentas.items ?? cuentas).length, "oportunidades abiertas:", abiertas.length);
await browser.close();
