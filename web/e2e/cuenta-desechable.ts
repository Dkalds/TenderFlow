/**
 * Una cuenta recién creada por test, para los recorridos que escriben.
 *
 * Todos los specs comparten la BD sembrada, y varios miran las pantallas de
 * `demo@tenderflow.dev` tal y como las deja el seed (`visual.spec.ts` las
 * compara con una captura). Un recorrido que abre una oportunidad, crea una
 * regla o descarta una señal con ese usuario le cambia el tablero, la campana
 * y el Radar al resto de la suite. Aquí cada test trabaja con una cuenta que
 * nadie más ve: los expedientes del seed son globales y los lee cualquiera;
 * oportunidades, reglas, cuentas objetivo, perfil y descartes son del usuario
 * o de su organización personal, que nace con el alta.
 *
 * Uso: importar `test` y `expect` de aquí en vez de `@playwright/test`. El
 * `page` de siempre llega ya con la sesión de la cuenta nueva:
 *
 *     import { test, expect } from "./cuenta-desechable";
 *     test("…", async ({ page, cuenta }) => { … });
 *
 * No se borra al acabar: la BD del job es efímera, y lo que deja una cuenta
 * que nadie vuelve a abrir no lo ve ningún otro spec. Además, con
 * `--repeat-each` y con los reintentos cada pasada estrena cuenta, así que un
 * test no hereda lo que dejó a medias su intento anterior.
 *
 * El alta self-service la abre `ALLOW_SELF_REGISTRATION`, declarada en el job
 * `frontend-e2e` de `ci.yml`; el porqué de cada detalle del alta (el dominio,
 * el largo de la contraseña) está contado en el test del borrado RGPD de
 * `critical-workflows.spec.ts`, de donde sale este patrón.
 */

import { test as base, expect as expectBase } from "@playwright/test";

type EstadoDeSesion = Awaited<ReturnType<import("@playwright/test").APIRequestContext["storageState"]>>;

export interface CuentaDesechable {
  email: string;
  nombre: string;
  /** Las cookies que dejó el alta: la sesión con la que arranca `page`. */
  estado: EstadoDeSesion;
}

/** Sesión vacía, dicha explícitamente: ver el comentario de `cuenta`. */
const SIN_SESION = { cookies: [], origins: [] };

export const test = base.extend<{ cuenta: CuentaDesechable }>({
  cuenta: async ({ playwright, baseURL }, entregar, testInfo) => {
    // `storageState` vacío a propósito: dentro de un test, los contextos que
    // se crean a mano heredan las opciones del proyecto, y la del proyecto
    // `chromium` es la sesión de demo. El alta la pisaría con su `Set-Cookie`,
    // pero entonces la limpieza del contexto dependería de que lo hiciera.
    const api = await playwright.request.newContext({ baseURL, storageState: SIN_SESION });
    try {
      // Única entre ejecuciones (el sello), entre tests de la misma pasada (el
      // índice del worker y el azar) y entre reintentos y repeticiones del
      // mismo test, que comparten título.
      const sello = `${Date.now()}-${testInfo.workerIndex}-${testInfo.repeatEachIndex}-${testInfo.retry}`;
      const azar = Math.random().toString(36).slice(2, 10);
      const email = `e2e-recorrido-${sello}-${azar}@example.com`;
      // Generada en ejecución: una constante con pinta de contraseña la marca
      // gitleaks. Pasa de los 16 caracteres que exige la política.
      const password = `E2E-${sello}-${azar}-Ok`; // pragma: allowlist secret
      const nombre = "Recorrido E2E";

      const alta = await api.post("/api/v1/auth/register", {
        data: { email, password, display_name: nombre },
      });
      expectBase(
        alta.status(),
        `POST /auth/register devolvió ${alta.status()}: ${(await alta.text()).slice(0, 300)}. ` +
          "¿Lleva la API `ALLOW_SELF_REGISTRATION=1`?",
      ).toBe(201);

      await entregar({ email, nombre, estado: await api.storageState() });
    } finally {
      await api.dispose();
    }
  },

  // La sesión del contexto del test es la de la cuenta nueva, no la de demo
  // que fija el proyecto: así `page`, `context` y `request` son los de siempre
  // y los specs se escriben como sus vecinos.
  storageState: async ({ cuenta }, entregar) => {
    await entregar(cuenta.estado);
  },

  page: async ({ page, cuenta }, entregar) => {
    // El seguro de todo lo anterior. Si un cambio de Playwright o de la
    // configuración hiciera que la sesión del proyecto ganase a la de arriba,
    // estos recorridos escribirían sobre el usuario del seed sin que nada
    // fallase aquí: fallarían otros specs, más tarde y por otro motivo.
    const yo = await page.request.get("/api/v1/auth/me");
    expectBase(yo.ok(), `GET /auth/me devolvió ${yo.status()} con la cuenta recién creada`).toBe(true);
    expectBase(((await yo.json()) as { email: string }).email, "el test no está usando su cuenta desechable").toBe(
      cuenta.email,
    );
    await entregar(page);
  },
});

/**
 * El `expect` de estos recorridos espera hasta 15 s en vez de 5.
 *
 * Casi todo lo que afirman llega tras una escritura y la relectura que la
 * sigue, y el runner de CI es bastante más lento que un portátil. Una espera
 * larga solo cuesta cuando la afirmación falla: si se cumple, vuelve en el
 * acto, y las negativas (`toHaveCount(0)`) también.
 */
export const expect = expectBase.configure({ timeout: 15_000 });

/**
 * Presupuesto de un recorrido corto. Los 30 s por defecto les sobran en un
 * portátil (tardan entre 2 y 5 s), pero con esperas de hasta 15 s por
 * afirmación y dos o tres recargas, un runner lento agotaría el reloj del
 * test antes que el de la afirmación que de verdad falla, y el informe
 * señalaría la línea equivocada.
 */
export const PRESUPUESTO_RECORRIDO_MS = 60_000;
