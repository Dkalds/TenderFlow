import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import jsxA11y from "eslint-plugin-jsx-a11y";

// Set recomendado de jsx-a11y, pero como warnings: el proyecto sigue una
// estrategia de limpieza progresiva (ver `no-explicit-any` más abajo). Endurecer
// a "error" de golpe bloquearía CI con ~20 violaciones heredadas en componentes
// shadcn/ui vendored. Convertirlas a warning las hace visibles sin romper el build.
const jsxA11yRecommendedAsWarn = Object.fromEntries(
  Object.keys(jsxA11y.configs.recommended.rules).map((rule) => [rule, "warn"]),
);

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Código autogenerado — no debe lintarse.
    "src/generated/**",
  ]),
  // Accessibility rules.
  // El plugin `jsx-a11y` ya lo registra `eslint-config-next/core-web-vitals`;
  // re-declararlo en flat config lanza "Cannot redefine plugin". Solo aplicamos
  // el set recommended de reglas (las claves `jsx-a11y/*` resuelven al plugin ya
  // registrado por Next).
  {
    rules: {
      ...jsxA11yRecommendedAsWarn,
      // `label-has-for` está **deprecada** por jsx-a11y (redundante con
      // `label-has-associated-control`, que sí cubre los casos reales). La
      // apagamos para no duplicar ~29 warnings de ruido.
      "jsx-a11y/label-has-for": "off",
    },
  },
  // Stricter rules
  {
    rules: {
      // Warn on explicit any to progressively eliminate them
      "@typescript-eslint/no-explicit-any": "warn",
      // Exhaustive deps en hooks: warning por ahora (limpieza progresiva).
      // Hay ~36 violaciones heredadas; arreglarlas a ciegas como error puede
      // introducir bugs (loops/stale closures), así que se tratan como deuda.
      "react-hooks/exhaustive-deps": "warn",
      // Reglas del React Compiler (eslint-plugin-react-hooks v6): deuda heredada
      // que la config rota nunca ejecutó. Como warning hasta limpiarlas una a una
      // (arreglarlas a ciegas puede cambiar comportamiento). Ver IMPROVEMENT_BACKLOG.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/purity": "warn",
      "react-hooks/immutability": "warn",
      // Prevent unused variables (ignore _ prefixed)
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
]);

export default eslintConfig;
