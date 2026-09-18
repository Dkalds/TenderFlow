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
      // 2026-09-07 (C7.2 / S5.8): sexto intento, mismo desenlace. El ítem pide
      // un piso propio para `src/app/**` «al valor medido», y **ese valor sigue
      // sin poder medirse en esta máquina**: `vitest run --coverage` sobre los
      // 109 ficheros se queda sin emitir una sola línea y hay que matarlo.
      //
      // No se puso un piso proyectado, y se hizo bien: la aritmética sobre las
      // tres carpetas medidas habría sido inventarse el número que el ítem pide
      // medir. Lo que faltaba era el número de CI, y ese llegó — ver el bloque
      // de abajo. La otra mitad del ítem (axe sobre la superficie pública,
      // incluida la ficha) está en `web/e2e/accessibility.spec.ts`.
      // 2026-09-08 (C7.2 / S5.8): **el número apareció**, y no en esta máquina.
      // El séptimo intento local murió igual que los seis anteriores, pero el
      // job `frontend` de CI sí corre la cobertura entera y publica su `lcov`
      // como artefacto. Descargándolo y agregándolo por subárbol sale:
      //
      //   src/app/**   lines 35.06 (1489/4247) · functions 30.15 (572/1897)
      //                branches 30.74 (1480/4814)
      //
      // Que la agregación es correcta no es una suposición: el mismo cálculo
      // sobre `src/hooks/**` da 69.32 / 61.21 / 67.86, y vitest había reportado
      // 69.31 / 61.2 en ese mismo run. Se reproduce su número antes de fiarse
      // del que no se puede contrastar.
      //
      // `statements` **no** se fija para `src/app/**`, a propósito. El `lcov` no
      // lo lleva, y derivarlo de `lines` sería inventarlo: en este mismo run
      // `src/hooks/**` tiene statements POR ENCIMA de lines (70.51 vs 69.31) y
      // el global POR DEBAJO (52.82 vs 53.48), o sea que no hay relación fija
      // que aplicar. Lo publica vitest la primera vez que este umbral corra en
      // CI, y entonces añadirlo es una línea.
      // 2026-09-18 (S7.1 / P1 de cobertura): **el octavo intento local sí
      // terminó**. `npx vitest run --coverage` con el pool por defecto: 199
      // ficheros, 2.198 tests, 161 s, exit 0. Es la primera medición local
      // completa desde 2026-08-10, y de ella salen todos los pisos de abajo con
      // el buffer de siempre (~2-3 puntos):
      //
      //   global       56.45 stmts / 48.45 branches / 51.45 funcs / 57.15 lines
      //   src/app/**   39.27 / 34.54 / 34.44 / 39.47
      //   src/lib/**   93.05 / 87.00 / 94.82 / 94.65
      //   src/hooks/** 77.50 / 66.79 / 72.49 / 77.15
      //   src/components/** 71.66 / 64.02 / 68.66 / 73.94
      //
      // `src/app/**` gana además su piso de `statements`, que el lcov de CI no
      // traía y ahora sí está medido. Ningún piso por carpeta baja; el de
      // branches de `src/hooks/**` se queda en 66 porque lo medido (66.79) no
      // deja buffer para subirlo.
      thresholds: {
        statements: 54,
        branches: 46,
        functions: 49,
        lines: 55,
        "src/lib/**": { statements: 91, branches: 85, functions: 92, lines: 92 },
        "src/hooks/**": { statements: 75, branches: 66, functions: 70, lines: 75 },
        "src/components/**": { statements: 69, branches: 61, functions: 66, lines: 71 },
        // Solo sube: `src/app/**` es donde viven las páginas cliente que durante
        // meses estuvieron fuera del denominador, y este piso es lo que impide
        // que vuelvan a salirse sin que nadie lo decida.
        "src/app/**": { statements: 37, branches: 32, functions: 32, lines: 37 },
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
