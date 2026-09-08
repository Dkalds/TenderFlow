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
    // Reportes, trazas y adjuntos generados por Playwright.
    "playwright-report/**",
    "test-results/**",
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
  // Dos invariantes de `src/lib/**` como única fuente, en un solo bloque: en
  // flat config el último `rules` que declara una regla gana entera, así que
  // partirlos en dos bloques con el mismo `files` desactivaría el primero.
  //
  // 1. El formato de datos vive en `src/lib/utils.ts` y en ningún otro sitio.
  //
  // Hubo una época de cinco formateadores de euros distintos, cada uno con su
  // criterio de redondeo, y el arreglo fue centralizarlos. Sin una regla que lo
  // sostenga, la dispersión vuelve por goteo: cada componente que necesita una
  // fecha con hora se escribe su `Intl.DateTimeFormat`. Si falta un helper
  // (p. ej. fecha + hora), añadilo a `lib/utils.ts` en vez de inlinearlo.
  //
  // 2. La API se consume por el cliente único de `src/lib/api-client.ts`.
  //
  // Había ~30 `fetch("/api/…")` crudos repartidos por 14 ficheros. Ninguno
  // redirigía a /login en 401, ninguno normalizaba el error a `ApiError`,
  // ninguno extraía el `detail` RFC-7807 y ninguno adjuntaba el CSRF que el
  // backend exige a toda mutación por cookie — el borrado RGPD de la cuenta
  // devolvía 403 exactamente por eso. Los helpers (`apiGet`, `apiMutate`,
  // `fetchWithAuth`, `fetchBlobWithAuth`) hacen las cuatro cosas en un sitio.
  //
  // `src/lib/**` queda exento porque es donde viven esos helpers y los tres
  // casos que no pueden pasar por ellos: el stream SSE de `ask-stream.ts`, la
  // descarga por blob de `export.ts` y el envío de `report-error.ts`.
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/lib/**", "src/**/__tests__/**", "src/**/*.test.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "CallExpression[callee.name='fetch'] > Literal:first-child[value=/^\\/api\\//]",
          message:
            "Usá el cliente de @/lib/api-client (apiGet, apiMutate, fetchWithAuth, fetchBlobWithAuth). Un fetch crudo a /api no redirige en 401, no normaliza el error a ApiError, no extrae el detail RFC-7807 y no adjunta el CSRF.",
        },
        {
          selector:
            "CallExpression[callee.name='fetch'] > TemplateLiteral:first-child > TemplateElement:first-child[value.raw=/^\\/api\\//]",
          message:
            "Usá el cliente de @/lib/api-client (apiGet, apiMutate, fetchWithAuth, fetchBlobWithAuth). Un fetch crudo a /api no redirige en 401, no normaliza el error a ApiError, no extrae el detail RFC-7807 y no adjunta el CSRF.",
        },
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
  // ── Tamaño de fichero en `src/app/**` (S7.1 del plan 2026-09 v2) ──────────
  //
  // El §1 de ese plan contó doce ficheros de `src/app` por encima de 300
  // líneas y los llamó «la deuda que hace frágil cualquier pantalla nueva»:
  // una vista de 900 líneas no se revisa, no se prueba por partes y obliga a
  // leerla entera para cambiar un botón. Al medirlo de verdad no eran doce
  // sino veintiocho. Hoy queda el de la allowlist de abajo.
  //
  // `skipBlankLines`/`skipComments` en `false` a propósito: el objetivo es que
  // el fichero se pueda leer de una sentada, y un comentario largo también se
  // lee. Este repo documenta mucho en comentarios —bien— y descontarlos
  // convertiría el límite en un incentivo para no explicar nada.
  //
  // Los tests quedan fuera: un fichero de tests largo es una tabla de casos, y
  // partirlo por longitud dispersa el criterio en vez de aclararlo.
  {
    files: ["src/app/**/*.ts", "src/app/**/*.tsx"],
    ignores: ["**/__tests__/**", "**/*.test.ts", "**/*.test.tsx"],
    rules: {
      "max-lines": [
        "error",
        { max: 300, skipBlankLines: false, skipComments: false },
      ],
    },
  },
  // ALLOWLIST — **vacía desde el 2026-09-08, y así se queda**. Solo podía
  // encoger, y encogió hasta desaparecer: los cuatro ficheros que crecieron el
  // 2026-09-06 durante la ejecución del plan están partidos. El login reparte
  // sus cinco caminos de entrada entre `login/_hooks/` y `login/_components/`;
  // los webhooks, sus piezas entre `ops/_components/webhooks/` y
  // `ops/_hooks/use-webhooks-ambito.ts`; las reglas de watchlist separan
  // formas, catálogos y coincidencias del módulo que traduce formulario ↔
  // contrato; y `/equipo` baja sus cinco bloques a `equipo/_components/` con
  // las etiquetas en `equipo/_lib/etiquetas.ts`.
  //
  // No se le añaden entradas: si una pantalla nueva no cabe en 300 líneas, se
  // parte antes de mergearla. Reabrir esta lista es volver a tener deuda sin
  // dueño, que es exactamente lo que costó cerrarla.

  // ── `title=` nativo fuera de los elementos HTML (C7.4) ──────────────────
  //
  // El atributo `title` no se dispara con teclado, su temporización no es
  // controlable y su estilo no sigue el tema. `components/ui/tooltip.tsx`
  // existe con la política de delay ya afinada (`docs/frontend-motion.md`).
  //
  // La regla mira SÓLO elementos HTML (`<span>`, `<div>`, `<button>`…). Un
  // `title` sobre un componente propio —`<KpiCard title="…">`— es su API, no
  // el atributo, y prohibirlo sería una regla que alguien acabaría
  // desactivando. La diferencia importa: de los 178 `title=` que un grep
  // cuenta hoy, **116 son props de componente** y sólo 34 son el atributo.
  //
  // `abbr` e `iframe` quedan fuera: en el primero el tooltip nativo ES la
  // semántica de la abreviatura, y en el segundo es el nombre accesible del
  // marco.
  //
  // `ignores` es la deuda de hoy y **sólo puede encoger**. Cada fichero que
  // sale de la lista es una ola cerrada; ninguno vuelve a entrar.
  //
  // 2026-09-08 — las rutas cambian sin que la deuda crezca. El plan de
  // arquitectura v2 partió por tamaño (S7.1) nueve de las vistas listadas, y el
  // `title=` se fue con el trozo que se llevó el markup: `tecnologias-view` →
  // `tecnologias-{detalle,heatmap,tablas}`, `tendencias-view` →
  // `tendencias-heatmap`, `observabilidad-view` →
  // `observabilidad/estado-global-row`, `contexto-strip` →
  // `contexto/mercado-strip`, `detalle/page` → `detalle/_components/*`,
  // `calendario-view` → `calendario-heatmap`, `clusters-view` →
  // `clusters-tablas`, `proyectos-modulos-view` → `proyectos-tablas`,
  // `competidores-view` → `competidores-{bajas,heatmap}`, y los de `empresas`
  // y `mercado/organo-top-scored` nacieron ya partidos del mismo movimiento.
  // Las nueve entradas viejas salen porque sus ficheros ya no tienen ninguno.
  //
  // El conteo sigue siendo el de la ola de C7.4 —31 atributos aquí más los que
  // quedan en los ocho ficheros que no se tocaron—, no uno nuevo. La siguiente
  // ola es la que los convierte a `Tooltip`.
  {
    files: ["src/**/*.tsx"],
    ignores: [
      "src/app/(dashboard)/competencia/_components/competidores-bajas.tsx",
      "src/app/(dashboard)/competencia/_components/competidores-heatmap.tsx",
      "src/app/(dashboard)/detalle/_components/detalle-fila.tsx",
      "src/app/(dashboard)/detalle/_components/detalle-pie.tsx",
      "src/app/(dashboard)/empresas/_components/context-line.tsx",
      "src/app/(dashboard)/empresas/_components/empresa-perfil-piezas.tsx",
      "src/app/(dashboard)/empresas/_components/empresa-perfil.tsx",
      "src/app/(dashboard)/empresas/_components/maestro-list.tsx",
      "src/app/(dashboard)/empresas/_components/review-queue.tsx",
      "src/app/(dashboard)/mercado/_components/calendario-heatmap.tsx",
      "src/app/(dashboard)/mercado/_components/clusters-tablas.tsx",
      "src/app/(dashboard)/mercado/_components/organo-top-scored.tsx",
      "src/app/(dashboard)/mercado/_components/proyectos-tablas.tsx",
      "src/app/(dashboard)/mercado/_components/tecnologias-detalle.tsx",
      "src/app/(dashboard)/mercado/_components/tecnologias-heatmap.tsx",
      "src/app/(dashboard)/mercado/_components/tecnologias-tablas.tsx",
      "src/app/(dashboard)/mercado/_components/tendencias-heatmap.tsx",
      "src/app/(dashboard)/ops/_components/observabilidad/estado-global-row.tsx",
      "src/app/(dashboard)/resumen/_components/contexto-strip.tsx",
      "src/app/(dashboard)/resumen/_components/contexto/mercado-strip.tsx",
      "src/components/competitors/company-awards.tsx",
      "src/components/competitors/company-profile-summary.tsx",
      "src/components/competitors/company-quick-view.tsx",
      "src/components/competitors/company-year-trend.tsx",
      "src/components/layout/space-shell.tsx",
      "src/components/pursuits/pursuit-comments.tsx",
      "src/components/source-freshness-panel.tsx",
    ],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "JSXOpeningElement[name.type='JSXIdentifier'][name.name=/^[a-z]/]:not([name.name='abbr']):not([name.name='iframe']) > JSXAttribute[name.name='title']",
          message:
            "El `title` nativo no se abre con teclado ni sigue el tema. Usá `Tooltip` (@/components/ui/tooltip) para texto informativo, o `aria-label` si lo que falta es el nombre accesible del control.",
        },
      ],
    },
  },
]);

export default eslintConfig;
