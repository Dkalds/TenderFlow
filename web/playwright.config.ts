import { defineConfig, devices } from "@playwright/test";
import { STORAGE_STATE_USER } from "./e2e/fixtures";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 1,
  // Un solo worker en CI: los specs comparten la BD sembrada.
  workers: process.env.CI ? 1 : 2,
  reporter: "html",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    // Inicia sesión una vez y deja las cookies en playwright/.auth/.
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], storageState: STORAGE_STATE_USER },
      dependencies: ["setup"],
    },
    // Firefox y WebKit quedan para ejecución local (`--project=firefox`). El
    // job bloqueante corre solo chromium: estos specs verifican lógica de
    // aplicación contra datos reales, no diferencias entre motores, y WebKit
    // en CI aporta sobre todo flakes.
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"], storageState: STORAGE_STATE_USER },
      dependencies: ["setup"],
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"], storageState: STORAGE_STATE_USER },
      dependencies: ["setup"],
    },
  ],
  webServer: {
    // En CI el build es un paso propio del workflow (necesita `API_BASE_URL`
    // horneado en tiempo de build), así que aquí solo se arranca el servidor.
    // En local, `dev` recompila al vuelo.
    command: process.env.CI ? "npm run start" : "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
});
