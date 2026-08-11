import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/generated/**",
        "src/test/**",
        "src/**/*.test.{ts,tsx}",
        "src/**/*.spec.{ts,tsx}",
        // Solo el chrome del App Router: layouts, estados de carga/error y
        // páginas de servidor. Aquí SÍ aplica el argumento de que los ejercita
        // el E2E de Playwright.
        //
        // `src/app/**` entero estuvo excluido con esa misma justificación, y era
        // falsa: 34 de las 37 páginas son `"use client"`, no Server Components,
        // y ahí viven ~18.700 de las ~44.700 líneas del frontend —incluidas
        // páginas de más de 1.000 líneas con toda la lógica de filtros y
        // mutaciones. El umbral que CI hacía cumplir se medía sobre el 58% del
        // código, lo que hacía el número más tranquilizador que informativo.
        "src/app/**/layout.tsx",
        "src/app/**/loading.tsx",
        "src/app/**/error.tsx",
        "src/app/**/not-found.tsx",
        "src/app/global-error.tsx",
        "src/middleware.ts",
      ],
      // Piso de cobertura enforced en CI (job `frontend`). Se fija ~2-3 pts por
      // debajo del real medido para dejar buffer anti-flapping. Solo subir,
      // nunca bajar: si añadís tests, subí el piso; si lo bajás, algo se rompió.
      //
      // 2026-08: los umbrales globales BAJAN de 68/63/68/70 a 38/28/35/39 y eso
      // NO es una relajación — es que el denominador dejó de mentir. Aquellos
      // números se medían con `src/app/**` entero excluido, o sea sobre el 58%
      // del código; medido sobre todo, lo real es 40.2/30.4/37.5/41.6. Para que
      // el cambio no pueda tapar una regresión en lo que sí estaba cubierto, los
      // pisos por carpeta de abajo conservan la garantía anterior sobre
      // lib/hooks/components: el global cubre el conjunto, y esos cubren el
      // subconjunto que ya se medía. Subir el global exige tests de páginas.
      thresholds: {
        statements: 38,
        branches: 28,
        functions: 35,
        lines: 39,
        // Medido 2026-08 (agregado de cada árbol completo, subcarpetas incluidas):
        // lib 93.8/85.9/95.2/94.8 · hooks 76.0/69.8/67.3/75.9 ·
        // components 66.2/60.4/64.6/68.2.
        "src/lib/**": { statements: 90, branches: 82, functions: 92, lines: 91 },
        "src/hooks/**": { statements: 72, branches: 66, functions: 64, lines: 72 },
        "src/components/**": { statements: 64, branches: 58, functions: 62, lines: 66 },
      },
      reporter: ["text", "text-summary", "lcov"],
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
