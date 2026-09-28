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
      "Usa el cliente de @/lib/api-client (apiGet, apiMutate, fetchWithAuth, fetchBlobWithAuth). Un fetch crudo a /api no redirige en 401, no normaliza el error a ApiError, no extrae el detail RFC-7807 y no adjunta el CSRF.",
  },
  {
    selector:
      "CallExpression[callee.name='fetch'] > TemplateLiteral:first-child > TemplateElement:first-child[value.raw=/^\\/api\\//]",
    message:
      "Usa el cliente de @/lib/api-client (apiGet, apiMutate, fetchWithAuth, fetchBlobWithAuth). Un fetch crudo a /api no redirige en 401, no normaliza el error a ApiError, no extrae el detail RFC-7807 y no adjunta el CSRF.",
  },
  {
    selector:
      "NewExpression[callee.object.name='Intl'][callee.property.name=/^(NumberFormat|DateTimeFormat|RelativeTimeFormat)$/]",
    message:
      "Usa los helpers de @/lib/utils (formatCurrency, formatNumber, formatDate…). Si falta uno, añádelo allí.",
  },
  {
    selector:
      "CallExpression[callee.property.name=/^(toLocaleString|toLocaleDateString|toLocaleTimeString)$/]",
    message:
      "Usa los helpers de @/lib/utils (formatNumber, formatDate…) en vez de toLocaleString.",
  },
];

// ── Aspecto de plantilla (auditoría anti-vibecode del 2026-09-26) ──────────
//
// La consola se leía como UI generada por plantilla, y no por sus valores de
// base —la paleta, la escala `tf-*`, los paneles planos estaban bien
// decididos— sino porque **nada hacía cumplir esas decisiones**: la misma pieza
// se dibujaba de 2 a 6 maneras, con 18 tamaños de letra escritos a mano, y los
// adornos que la portada ya había retirado seguían dentro. La migración del
// 2026-09-26/27 dejó cada una de estas cifras a cero (medidas y comandos en
// docs/UX_AUDIT.md, «Aspecto de plantilla en la consola»; las «reglas» que se
// citan abajo son las de su apartado «Las reglas de la casa»). Estas restricciones
// existen para que se queden ahí: **no tienen allowlist**, porque no hay deuda
// que listar. Un caso legítimo nuevo se justifica en su línea
// (`// eslint-disable-next-line no-restricted-syntax -- <por qué>`), como hace
// `connection-banner.tsx`, y se ve en el diff.
//
// Solo miran literales (cadenas, plantillas y texto JSX): un comentario que
// cita la clase retirada para explicar por qué se fue no cuenta.
//
// Se aplican a todo `src` salvo los tests —que sí las nombran, para asertar su
// ausencia— y por eso van en los dos bloques de arriba **y** en uno propio de
// `src/lib`, que las cuatro de arriba dejan fuera.
const CLASE = (patron) => [
  { selector: `Literal[value=/${patron}/]` },
  { selector: `TemplateElement[value.raw=/${patron}/]` },
];
const conMensaje = (message, selectores) => selectores.map((s) => ({ ...s, message }));

const restriccionesDeAspecto = [
  // Regla 1 de la casa: la escala son seis pasos (`text-tf-micro`… `text-tf-hero`,
  // más `text-xs`/`text-sm`). Llegó a haber 451 tamaños a mano en 18 valores.
  ...conMensaje(
    "Tamaño de letra a mano: usa la escala (text-tf-micro 11 · text-tf-meta 12 · text-tf-body 13 · text-sm 14 · text-tf-lede 15 · text-tf-title 20 · text-tf-hero 32). El mapa está en el comentario de la escala de globals.css.",
    CLASE(String.raw`(?<![\w-])text-\[(?:[\d.]|length:|clamp\()`),
  ),
  // Reglas 2 y 3: el rótulo de dato va en sans, en frase, a 11 px. La receta
  // «mono + versal» era la voz de todo en la consola (53 líneas).
  ...conMensaje(
    "Rótulo en mono versal: usa ROTULO_DATO, SectionTitle, Fact o StatCell de @/components/console/panel (sans, en frase, 11 px). La versal solo va en CABECERA_COLUMNA de @/components/ui/table, y la mono solo en identificadores.",
    CLASE(String.raw`^(?=[\s\S]*(?<![\w-])font-mono(?![\w-]))(?=[\s\S]*(?<![\w-])uppercase(?![\w-]))`),
  ),
  // Utilidades borradas de globals.css: la clase no falla, se queda sin
  // estilo y el texto cae al del padre sin que nada avise.
  ...conMensaje(
    "Clase retirada de globals.css (no pinta nada): tf-display/tf-h1/tf-h2 → font-display text-tf-lede|title|hero; tf-kpi → text-tf-title font-semibold; tf-caption → text-tf-meta; tf-card-shadow → sin sombra (panel plano); tf-sidebar-surface → bg-card; tf-hero-grid y tf-fill-enter → nada.",
    CLASE(
      String.raw`(?<![\w-])tf-(?:display|h1|h2|kpi|caption|card-shadow|sidebar-surface|hero-grid|fill-enter)(?![\w-])`,
    ),
  ),
  // Regla 6: la paleta cruda de Tailwind (171 clases en 38 ficheros) esquivaba
  // los tokens ajustados por contraste en los dos temas.
  ...conMensaje(
    "Color de la paleta cruda de Tailwind: usa los tokens semánticos (success, warning, destructive, info, muted, primary), que ya cambian con el tema y están medidos por contraste (lib/__tests__/contraste-tokens.test.ts).",
    CLASE(
      String.raw`(?<![\w-])(?:bg|text|border|ring|fill|stroke|from|via|to|divide|outline|decoration|caret|accent|placeholder|shadow)-(?:red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-\d{2,3}(?![\w-])`,
    ),
  ),
  // Regla 7: tres radios con papel. `rounded` a secas son los 4 px por
  // defecto de Tailwind, fuera de la escala de la casa.
  ...conMensaje(
    "Radio fuera de la escala: controles, chips y badges rounded-md; paneles rounded-xl; puntos y avatares rounded-full; rounded-sm donde iba el `rounded` desnudo. Nada de rounded-2xl, rounded-3xl ni rounded-[Npx].",
    CLASE(String.raw`(?<![\w-])rounded(?:-(?:2xl|3xl|\[[^\]]*\]))?(?![\w-])`),
  ),
  // Regla 5: panel opaco. `bg-card/70` sobre un fondo plano no deja ver nada
  // detrás: solo da un segundo blanco (44 usos). Las capas que flotan sobre
  // contenido lo justifican en su línea.
  ...conMensaje(
    "Panel translúcido sobre fondo plano: los paneles van en bg-card opaco. Si es una capa flotante sobre contenido que se desplaza, justifícalo en la línea (eslint-disable-next-line con el motivo).",
    CLASE(String.raw`(?<![\w-])bg-card\/(?:\d|\[)`),
  ),
  // Regla 14 y docs/frontend-motion.md: en Tailwind v4 `scale-*` y
  // `translate-*` escriben sus propias propiedades, y una lista con
  // `transform` no las anima: la pulsación saltaba sin transición.
  ...conMensaje(
    "transition-[…transform…] no anima scale-* ni translate-* en Tailwind v4: nombra la propiedad (transition-[scale,background-color], transition-[translate,color]) o usa transition-transform.",
    CLASE(String.raw`transition-\[[^\]]*(?<![\w-])transform(?![\w-])`),
  ),
  // Regla 14: nada de pulsos infinitos decorativos. El punto verde que latía
  // «en vivo» junto a datos de hace horas era la firma de la plantilla.
  ...conMensaje(
    "Animación infinita decorativa (animate-ping/animate-bounce): un estado se dice con color y texto, sin pulso. Carga: Skeleton; frescura: «Actualizado hace…».",
    CLASE(String.raw`(?<![\w-])animate-(?:ping|bounce)(?![\w-])`),
  ),
  // Regla 8: solo iconos de lucide. Un emoji o un glifo de dingbat hace de
  // icono sin tamaño, color ni nombre accesible de la casa (la ficha de
  // órgano llevaba 🏢 📉 📅 🏆). ©, ® y ™ son tipografía, no iconos.
  ...conMensaje(
    "Emoji o glifo como icono: usa un icono de lucide (mapa de conceptos en @/lib/iconos) con aria-hidden, o el texto. ✓ ✕ ● ○ tampoco: Check, X, Circle.",
    [
      String.raw`(?![©®™])\p{Extended_Pictographic}|[✓✕✗✘○●]`,
    ].flatMap((patron) => [
      { selector: `JSXText[value=/${patron}/u]` },
      { selector: `Literal[value=/${patron}/u]` },
      { selector: `TemplateElement[value.raw=/${patron}/u]` },
    ]),
  ),
];

// Módulos y nombres de import retirados. Mismo motivo que arriba.
//
// `Card`, `EmptyState` y `KpiCard` eran el vocabulario de shadcn que convivía con
// el de la consola (`components/console/panel`): 106, 28 y 14 importadores el
// 2026-09-26, cero el 2026-09-27. Los tres módulos siguen existiendo, deprecados,
// porque sus tests fijan cómo pintaban; importarlos desde código nuevo es lo
// que esta regla impide.
//
// `deudaCard` es la lista que `ui/card.tsx` prometía desde su comentario y que
// nunca se escribió. Nace vacía —la migración terminó antes que la regla— y
// **solo puede encoger**: se deja la constante, como `deudaTitleNativo`, para
// que una entrada nueva sea un cambio que se ve en el diff. Si alguna vez la
// tuviera, ese fichero necesitaría su propio bloque con el resto de rutas: en
// flat config el último bloque que declara una regla la gana entera.
const deudaCard = [];

const importacionesRetiradas = [
  {
    name: "@/components/ui/card",
    message:
      "Card está retirado de la consola: usa Panel, PanelTitle (y PanelLoading/PanelEmpty/PanelError) de @/components/console/panel, que fijan los tres estados al alto del contenido.",
  },
  {
    name: "@/components/ui/empty-state",
    message:
      "EmptyState está retirado: usa PanelEmpty de @/components/console/panel con un título y una pista concretos (sin props pintaba un vacío en blanco).",
  },
  {
    name: "@/components/charts/kpi-card",
    message:
      "KpiCard/KpiStrip están retirados: usa StatStrip y StatCell de @/components/console/panel (cifra a 20 px en sans, sin icono en baldosa).",
  },
  {
    // D5: la IA se nombra, no se adorna. Sparkles hacía de comodín para «IA»,
    // «nuevo» y «buscar» (7 ficheros); la varita es la misma metáfora.
    name: "lucide-react",
    importNames: [
      "Sparkle",
      "SparkleIcon",
      "LucideSparkle",
      "Sparkles",
      "SparklesIcon",
      "LucideSparkles",
      "WandSparkles",
      "WandSparklesIcon",
      "LucideWandSparkles",
      "PencilSparkles",
      "PencilSparklesIcon",
      "LucidePencilSparkles",
      "Wand",
      "WandIcon",
      "LucideWand",
      "Wand2",
      "Wand2Icon",
      "LucideWand2",
    ],
    message:
      "La IA se nombra, no se adorna (D5): nada de Sparkles ni varitas. Si hace falta un glifo, MessageSquareText o TextSearch en text-muted-foreground (mapa en @/lib/iconos).",
  },
  {
    // Regla 8: el icono se elegía por la palabra («importe» → dólar) en un
    // producto en euros (5 ficheros).
    name: "lucide-react",
    importNames: [
      "DollarSign",
      "DollarSignIcon",
      "LucideDollarSign",
      "CircleDollarSign",
      "CircleDollarSignIcon",
      "LucideCircleDollarSign",
    ],
    message: "Un importe en euros no lleva icono de dólar: sin icono (la cifra ya lo dice) o Euro. Mapa en @/lib/iconos.",
  },
  {
    // `AlertTriangle` es el nombre viejo de `TriangleAlert` en lucide: con los
    // dos en el árbol (15 ficheros), el mismo aviso se importaba de dos formas.
    name: "lucide-react",
    importNames: ["AlertTriangle", "AlertTriangleIcon", "LucideAlertTriangle"],
    message: "Usa TriangleAlert (el nombre vigente en lucide): un mismo icono, un mismo nombre.",
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
    "El `title` nativo no existe para teclado ni táctil: usa <Tooltip> (@/components/ui/tooltip) en controles y <Pista> (@/components/ui/pista) en texto y celdas. En <abbr> e <iframe> sí es semántico y está permitido.",
};

//: Ficheros con `title=` nativo. **Solo puede encoger**, y desde el
//: 2026-09-18 está vacía: los 36 que quedaban (22 ficheros, casi todos celdas
//: de tabla y heatmaps) se migraron. Los controles —que ya eran focusables— a
//: `<Tooltip>`; el texto truncado y las casillas de heatmap a `<Pista>`
//: (`components/ui/pista.tsx`), cuyo disparador **no** es focusable: la rejilla
//: no gana una parada de tabulación por celda, y lo que el teclado necesita va
//: en el texto (recorte por CSS, `sr-only` o `aria-label`).
//:
//: Se deja la constante —vacía— en vez de borrarla para que un `title=` nuevo
//: no pueda volver por la vía de «añadir una línea a la lista»: añadirla es un
//: cambio que se ve en el diff. `scripts/check_title_attrs.py` tiene el techo a 0.
const deudaTitleNativo = [];

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
      //
      // `depth: 3` (la regla mira dos niveles por defecto): una celda con el
      // texto envuelto en `<Pista>` —el sustituto de `title=`— queda
      // `td > Pista > span > {texto}`, tres niveles. Con el defecto la regla
      // daba por «sin nombre» una celda cuyo texto está ahí.
      "jsx-a11y/control-has-associated-label": ["error", { depth: 3 }],
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
  // (p. ej. fecha + hora), añádelo a `lib/utils.ts` en vez de inlinearlo.
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
      "no-restricted-syntax": ["error", ...restriccionesDeSintaxis, ...restriccionesDeAspecto],
    },
  },
  // La quinta restricción, sobre los `.tsx` que ya no tienen `title` nativo.
  // Las cuatro de arriba (y las de aspecto) se repiten por referencia: sin
  // ellas, este bloque las desactivaría en todos estos ficheros (flat config:
  // el último bloque que declara la regla la gana entera).
  {
    files: ["src/**/*.tsx"],
    ignores: [
      "src/lib/**",
      "src/**/__tests__/**",
      "src/**/*.test.tsx",
      ...deudaTitleNativo,
    ],
    rules: {
      "no-restricted-syntax": [
        "error",
        ...restriccionesDeSintaxis,
        ...restriccionesDeAspecto,
        restriccionTitleNativo,
      ],
    },
  },
  // Las de aspecto también en `src/lib`, que los dos bloques de arriba dejan
  // fuera por el cliente de API y los formateadores: ahí viven constantes de
  // clases (`lib/forms/campo.tsx`, `lib/iconos.ts`) que pintan en toda la app.
  {
    files: ["src/lib/**/*.{ts,tsx}"],
    ignores: ["src/**/__tests__/**", "src/**/*.test.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": ["error", ...restriccionesDeAspecto],
    },
  },
  // Primitivos e iconos retirados (ver `importacionesRetiradas`). Los tests
  // quedan fuera: los de `card`, `empty-state` y `kpi-card` prueban el propio
  // módulo, y `navigation.test.ts` importa Sparkles para asertar su ausencia.
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/**/__tests__/**", "src/**/*.test.{ts,tsx}", ...deudaCard],
    rules: {
      "no-restricted-imports": ["error", { paths: importacionesRetiradas }],
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
]);

export default eslintConfig;
