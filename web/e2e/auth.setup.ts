/**
 * Autenticación previa a los specs: un login por usuario, no uno por test.
 *
 * Playwright ejecuta este proyecto antes que los demás (ver `dependencies` en
 * playwright.config.ts) y guarda las cookies en disco; el resto de specs
 * arrancan ya autenticados. Dos peticiones por ejecución en vez de treinta:
 * menos presión sobre el limitador y un único punto donde puede fallar el
 * login, con un mensaje claro cuando el backend no está.
 *
 * El POST va contra el proxy same-origin de Next (`/api/*`), no contra
 * `:8080` directo, así que de paso verifica que el rewrite está bien
 * configurado — si `API_BASE_URL` no llegó al build, esto falla aquí y no en
 * un spec cualquiera con un error incomprensible.
 */

import { test as setup, expect } from "@playwright/test";
import {
  ADMIN_USER,
  DEMO_USER,
  STORAGE_STATE_ADMIN,
  STORAGE_STATE_USER,
} from "./fixtures";

async function login(
  request: import("@playwright/test").APIRequestContext,
  credentials: { email: string; password: string },
  storagePath: string
) {
  const response = await request.post("/api/v1/auth/login", {
    data: { email: credentials.email, password: credentials.password },
  });

  expect(
    response.ok(),
    `Login de ${credentials.email} devolvió ${response.status()}. ` +
      `¿Está la API viva y la BD sembrada con \`python scripts/seed_dev.py --with-predicciones\`?`
  ).toBeTruthy();

  const state = await request.storageState();
  const sessionCookie = state.cookies.find((c) => c.name === "session");
  expect(
    sessionCookie,
    "El login no dejó cookie `session`: el resto de specs no estarían autenticados."
  ).toBeDefined();

  await request.storageState({ path: storagePath });
}

setup("autenticar usuario demo", async ({ request }) => {
  await login(request, DEMO_USER, STORAGE_STATE_USER);
});

setup("autenticar usuario admin", async ({ request }) => {
  await login(request, ADMIN_USER, STORAGE_STATE_ADMIN);
});
