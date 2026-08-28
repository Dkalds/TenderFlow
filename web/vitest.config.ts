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
      //
      // 2026-08-18: las páginas de más de 1.000 líneas ya no tienen la lógica
      // dentro del componente. `detalle`, `competidores` y `mi-watchlist` la
      // exportan desde `_hooks/` y esos módulos SÍ están medidos:
      //
      //   src/app/**/_hooks/*.ts  →  99.67 stmts / 95 branches / 100 funcs / 100 lines
      //                              (305/306 · 228/240 · 107/107 · 242/242)
      //   src/lib/ask-stream.ts   →  90.38/83.33/100/93.61  ⇒  100/96.29/100/100
      //
      // Los umbrales globales de abajo NO suben todavía, y es a propósito: el
      // denominador global no se pudo volver a medir en la máquina local (cuatro
      // intentos de `vitest run --coverage` sobre los 109 ficheros murieron con
      // `[vitest-pool]: Failed to start threads worker`, que reporta «no tests»
      // con exit 0 y una cobertura falsa del 0-14%). Proyectar 40.2/30.4/37.5/41.6
      // + los 305/228/107/242 medidos da ~45/34/42/46, pero eso es aritmética, no
      // una medición: subir el piso a un número no medido es justo lo que deja
      // CI en rojo. Súbanse los cuatro globales cuando el job `frontend` publique
      // su propio número, dejando el buffer de ~2-3 puntos de siempre.
      //
      // 2026-08-27: quinto intento, mismo desenlace. `vitest run --coverage`
      // muere con `Timeout terminating forks worker` sobre los 109 ficheros —con
      // el pool `forks` por defecto y también con `--pool=threads
      // --no-file-parallelism`— y remata con «no tests» y 0% en las cuatro
      // métricas, que es cobertura falsa, no cobertura cero. Los tests nuevos de
      // esta tanda (ida y vuelta del ámbito por la URL en
      // `lib/__tests__/filters.test.ts`, y los desenlaces del stream de `/ask`
      // en `ask-stream.test.ts`) pasan ejecutados en solitario, pero un fichero
      // que pasa no es un denominador global: los pisos siguen sin tocarse.
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
