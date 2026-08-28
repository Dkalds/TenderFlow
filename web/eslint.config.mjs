import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import jsxA11y from "eslint-plugin-jsx-a11y";

// Set recomendado de jsx-a11y endurecido a error: todas las violaciones fueron
// corregidas en la limpieza progresiva (2026-06-09). Bloquea regresiones en CI.
const jsxA11yRecommendedAsError = Object.fromEntries(
  Object.keys(jsxA11y.configs.recommended.rules).map((rule) => [rule, "error"]),
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
    // Informe HTML de cobertura (v8 lo escribe al correr `npm run
    // test:coverage`): lo genera una herramienta y no está versionado.
    "coverage/**",
  ]),
  // Accessibility rules.
  // El plugin `jsx-a11y` ya lo registra `eslint-config-next/core-web-vitals`;
  // re-declararlo en flat config lanza "Cannot redefine plugin". Solo aplicamos
  // el set recommended de reglas (las claves `jsx-a11y/*` resuelven al plugin ya
  // registrado por Next).
  {
    rules: {
      ...jsxA11yRecommendedAsError,
      // `label-has-for` está **deprecada** por jsx-a11y (redundante con
      // `label-has-associated-control`, que sí cubre los casos reales).
      "jsx-a11y/label-has-for": "off",
      // Fuera del set recommended, se sube a mano: es la que caza el botón
      // icon-only sin nombre accesible (WCAG 4.1.2). Los dos flechas de año del
      // Calendario se colaron precisamente porque nada lo verificaba, mientras
      // todos los demás `size="icon"` del repo sí llevan `aria-label`.
      "jsx-a11y/control-has-associated-label": "error",
    },
  },
  // Stricter rules
  {
    rules: {
      // Todas las violaciones resueltas (2026-06-09). Endurecidas a error.
      "@typescript-eslint/no-explicit-any": "error",
      // exhaustive-deps y React Compiler: todos resueltos o con eslint-disable
      // documentado. Endurecidos a error para bloquear nuevas regresiones.
      "react-hooks/exhaustive-deps": "error",
      "react-hooks/set-state-in-effect": "error",
      "react-hooks/purity": "error",
      "react-hooks/immutability": "error",
      // Prevent unused variables (ignore _ prefixed)
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  // El formato de datos vive en `src/lib/utils.ts` y en ningún otro sitio.
  //
  // Hubo una época de cinco formateadores de euros distintos, cada uno con su
  // criterio de redondeo, y el arreglo fue centralizarlos. Sin una regla que lo
  // sostenga, la dispersión vuelve por goteo: cada componente que necesita una
  // fecha con hora se escribe su `Intl.DateTimeFormat`. Si falta un helper
  // (p. ej. fecha + hora), añadilo a `lib/utils.ts` en vez de inlinearlo.
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/lib/**", "src/**/__tests__/**", "src/**/*.test.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "NewExpression[callee.object.name='Intl'][callee.property.name=/^(NumberFormat|DateTimeFormat|RelativeTimeFormat)$/]",
          message:
            "Usá los helpers de @/lib/utils (formatCurrency, formatNumber, formatDate…). Si falta uno, añadilo allí.",
        },
        {
          selector:
            "CallExpression[callee.property.name=/^(toLocaleString|toLocaleDateString|toLocaleTimeString)$/]",
          message:
            "Usá los helpers de @/lib/utils (formatNumber, formatDate…) en vez de toLocaleString.",
        },
      ],
    },
  },
]);

export default eslintConfig;
