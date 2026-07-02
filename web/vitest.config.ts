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
        // Next.js App Router pages/layouts/loading/error are Server Components
        // exercised via Playwright e2e (web/e2e), not unit tests. Excluding them
        // keeps the unit-coverage threshold meaningful for lib/hooks/components.
        "src/app/**",
        "src/middleware.ts",
      ],
      // Piso de cobertura enforced en CI (job `frontend`). Se fija ~2-3 pts por
      // debajo del real medido para dejar buffer anti-flapping. Solo subir,
      // nunca bajar: si añadís tests, subí el piso; si lo bajás, algo se rompió.
      thresholds: {
        statements: 68,
        branches: 63,
        functions: 68,
        lines: 70,
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
