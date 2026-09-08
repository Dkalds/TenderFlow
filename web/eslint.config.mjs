import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import jsxA11y from "eslint-plugin-jsx-a11y";

// Set recomendado de jsx-a11y endurecido a error: todas las violaciones fueron
// corregidas en la limpieza progresiva (2026-06-09). Bloquea regresiones en CI.
const jsxA11yRecommendedAsError = Object.fromEntries(
  Object.keys(jsxA11y.configs.recommended.rules).map((rule) => [rule, "error"]),
);


// Las cuatro restricciones de sintaxis que aplican a TODO `src` salvo `src/lib`
// y los tests. Viven en una constante porque hay dos bloques que las declaran:
// el de abajo, y el que añade la quinta (`title` nativo, C7.4) sobre un
// conjunto de ficheros más estrecho. En flat config el último bloque que
// declara una regla la gana **entera**, así que el segundo tiene que repetir
// estas cuatro o las desactivaría sin decirlo. Repetirlas copiándolas sería
// deuda esperando a divergir; repetirlas por referencia no puede divergir.
const restriccionesDeSintaxis = [
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
];

// Quinta restricción: `title=` sobre un elemento nativo es un tooltip
// inaccesible (C7.4).
//
// El atributo `title` de HTML no se puede enfocar con el teclado, no se puede
// abrir sin ratón y los lectores de pantalla lo anuncian de forma
// inconsistente. Cuando lleva la única copia de un dato —el nombre completo de
// un órgano truncado, la fecha exacta detrás de un «hace 3 días»— ese dato no
// existe para quien no usa ratón. `components/ui/tooltip.tsx` (Radix) sí lo es.
//
// `<abbr>` e `<iframe>` quedan fuera: ahí `title` es semántica del elemento (la
// expansión de la abreviatura, el nombre accesible del marco), no un tooltip.
//
// El selector exige etiqueta en minúscula porque eso es lo que distingue un
// elemento nativo de un componente en JSX: `<KpiCard title="…">` es una prop y
// no genera atributo HTML. Confundir las dos cosas es lo que hacía que el
// conteo por grep del plan diera 152 donde el problema real son 33
// (`scripts/check_title_attrs.py` mide el número real y hace de techo).
const restriccionTitleNativo = {
  selector:
    "JSXOpeningElement[name.type='JSXIdentifier'][name.name=/^[a-z]/]:not([name.name='abbr']):not([name.name='iframe']) > JSXAttribute[name.name='title']",
  message:
    "El `title` nativo no existe para teclado ni táctil: usá <Tooltip> de @/components/ui/tooltip. En <abbr> e <iframe> sí es semántico y está permitido.",
};

//: Ficheros con `title=` nativo. **Solo puede encoger**: al migrar uno a
//: `<Tooltip>`, borrá su línea. `scripts/check_title_attrs.py` impide que el
//: total suba, y es él quien manda: la lista de abajo dice *dónde* está la
//: deuda, el ratchet dice *cuánta*.
//:
//: Regenerada el 2026-09-08 (22 ficheros, 33 `title=`) al fusionar el plan
//: complementario sobre `master`. La lista anterior tenía 18 ficheros y once
//: de ellos ya no existían con ese nombre: #272/#274 partieron las vistas
//: grandes —`observabilidad-view.tsx` en `observabilidad/`, `contexto-strip.tsx`
//: en `contexto/`, `tecnologias-view.tsx` en tabla + heatmap + detalle— y la
//: misma deuda quedó en rutas nuevas que la lista no cubría, con ESLint en rojo
//: sin que nadie hubiera añadido un `title=`. Regenerar no es ampliar: el total
//: no sube, y de hecho bajó de 38 a 33 en el mismo cambio.
//:
//: Cinco salieron aquí (`space-shell` a `<abbr>`, que es donde `title` sí es
//: semántico; `estado-global-row`, `mercado-strip`, `eventos-feed` y
//: `pursuit-comments` a `<Tooltip>`). Los 33 que quedan están casi todos en
//: celdas de tabla y en heatmaps, donde el disparador tendría que ser una celda
//: focusable: eso cambia el orden de tabulación de la rejilla entera y se
//: decide mirando la pantalla, no leyendo el diff.
const deudaTitleNativo = [
      "src/app/(dashboard)/competencia/_components/competidores-bajas.tsx",
      "src/app/(dashboard)/competencia/_components/competidores-heatmap.tsx",
      "src/app/(dashboard)/detalle/_components/detalle-barra.tsx",
      "src/app/(dashboard)/detalle/_components/detalle-fila.tsx",
      "src/app/(dashboard)/detalle/_components/detalle-pie.tsx",
      "src/app/(dashboard)/empresas/_components/context-line.tsx",
      "src/app/(dashboard)/empresas/_components/empresa-perfil-piezas.tsx",
      "src/app/(dashboard)/empresas/_components/maestro-list.tsx",
      "src/app/(dashboard)/mercado/_components/calendario-heatmap.tsx",
      "src/app/(dashboard)/mercado/_components/clusters-tablas.tsx",
      "src/app/(dashboard)/mercado/_components/organo-top-scored.tsx",
      "src/app/(dashboard)/mercado/_components/organos-tabla.tsx",
      "src/app/(dashboard)/mercado/_components/proyectos-tablas.tsx",
      "src/app/(dashboard)/mercado/_components/tecnologias-detalle.tsx",
      "src/app/(dashboard)/mercado/_components/tecnologias-heatmap.tsx",
      "src/app/(dashboard)/mercado/_components/tecnologias-tablas.tsx",
      "src/app/(dashboard)/mercado/_components/tendencias-heatmap.tsx",
      "src/components/competitors/company-awards.tsx",
      "src/components/competitors/company-profile-summary.tsx",
      "src/components/competitors/company-quick-view.tsx",
      "src/components/competitors/company-year-trend.tsx",
      "src/components/source-freshness-panel.tsx",
];

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
      "no-restricted-syntax": ["error", ...restriccionesDeSintaxis],
    },
  },
  // La quinta restricción, sobre los `.tsx` que ya no tienen `title` nativo.
  // Las cuatro de arriba se repiten por referencia: sin ellas, este bloque las
  // desactivaría en todos estos ficheros (flat config: el último bloque que
  // declara la regla la gana entera).
  {
    files: ["src/**/*.tsx"],
    ignores: [
      "src/lib/**",
      "src/**/__tests__/**",
      "src/**/*.test.tsx",
      ...deudaTitleNativo,
    ],
    rules: {
      "no-restricted-syntax": ["error", ...restriccionesDeSintaxis, restriccionTitleNativo],
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
  // ALLOWLIST — **solo puede encoger**. No se le añaden entradas: si una
  // pantalla nueva no cabe en 300 líneas, se parte antes de mergearla.
  //
  // Los cuatro que quedaban crecieron el 2026-09-06, durante la propia
  // ejecución del plan, porque los streams S1 y S4 les añadieron superficie y
  // sus agentes no llegaron a trocearlas. Tres ya están partidos (2026-09-07):
  // el login reparte sus cinco caminos de entrada entre `login/_hooks/` y
  // `login/_components/`; los webhooks, sus piezas entre
  // `ops/_components/webhooks/` y `ops/_hooks/use-webhooks-ambito.ts`; y las
  // reglas de watchlist separan formas, catálogos y coincidencias del módulo
  // que traduce formulario ↔ contrato.
  //
  // Queda uno solo, y es deuda con fecha y con dueño, no un permiso permanente.
  {
    files: ["src/app/(dashboard)/equipo/page.tsx"],
    rules: { "max-lines": "off" },
  },
]);

export default eslintConfig;
