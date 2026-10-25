/**
 * Registro de páginas y su contrato de filtros globales.
 *
 * La NAVEGACIÓN (rail, vistas, redirects) vive en `lib/console-spaces.ts` +
 * `lib/space-views.ts` — única fuente desde la retirada del cromo heredado
 * (2026-08: breadcrumb, pestañas de sección y KPI bar, muertos al quedar
 * construidos los 14 espacios). Este módulo conserva lo que la consola sigue
 * consumiendo: el catálogo de páginas (`ALL_PAGES`/`findPage`, buscador ⌘K y
 * atajos) y el contrato de filtros por página que la barra de ámbito deriva —
 * para un espacio, vía las rutas que absorbe (`SPACE_VIEWS`).
 */

import { ESPACIOS_ABSORBIDOS, SPACE_VIEWS } from "@/lib/space-views";

export type GlobalFilterKey =
  | "q"
  | "fecha"
  | "ccaa"
  | "tecnologia"
  | "estado"
  | "importe"
  // F1.1 — sólo los aplica el listado (`GET /licitaciones`).
  | "procedimiento"
  | "provincia"
  | "importe_max";

/**
 * Filtros que una página tiene que **declarar** para verlos (F1.1).
 *
 * El resto del ámbito se asume aplicado cuando la página no dice lo contrario
 * (`globalFilterKeys` ausente = todos): es el comportamiento histórico y lo
 * cumplen porque sus endpoints aceptan esos parámetros. Estos tres no: hoy
 * sólo los entiende el listado, y un endpoint analítico que no los conoce los
 * ignora en silencio. Ofrecerlos en todas las pantallas sería pintar filtros
 * inertes, que es lo que la barra de ámbito existe para no hacer.
 */
export const FILTROS_OPT_IN: readonly GlobalFilterKey[] = ["procedimiento", "provincia", "importe_max"];

export interface NavPage {
  label: string;
  slug: string;
  /** Qué hay en la página, en lenguaje de usuario (se lee en el `title` de los atajos del Resumen). */
  description: string;
  /**
   * Contrato de filtros globales: si es `false`, la página NO consume el
   * estado de filtros (GlobalFilterBar y KPI bar se ocultan para no mentir).
   * Ausente equivale a `true`.
   */
  usesGlobalFilters?: boolean;
  /**
   * Subconjunto de filtros globales que la página aplica de verdad. Si se
   * define, la GlobalFilterBar muestra SOLO esos controles (aunque
   * `usesGlobalFilters` sea `false`, para no mostrar filtros inertes). El KPI
   * bar sigue gobernado por `usesGlobalFilters`.
   */
  globalFilterKeys?: GlobalFilterKey[];
  /**
   * Subconjunto de `globalFilterKeys` cuya selección reemplaza el valor
   * anterior en vez de acumularse en chips. Pensado para páginas de acción
   * como Radar, donde "varias tecnologías a la vez" no tiene un significado
   * operativo claro.
   */
  singleValueFilterKeys?: GlobalFilterKey[];
  /** Filtros de {@link FILTROS_OPT_IN} que la página aplica además del resto. */
  optInFilterKeys?: GlobalFilterKey[];
}

export interface NavSection {
  label: string;
  pages: NavPage[];
  /**
   * @deprecated No lo lee nadie: la visibilidad de la navegación real la
   * gobierna `ConsoleSpace.visibility` en `lib/console-spaces.ts`, que además
   * cubre el eje `experimental`. Se conserva mientras `SECTIONS` siga
   * describiendo el catálogo histórico de páginas; al retirarlo, borrar también
   * este campo.
   */
  adminOnly?: boolean;
}

export const SECTIONS: NavSection[] = [
  {
    label: "Radar",
    pages: [
      {
        label: "Radar",
        slug: "radar",
        // Ni "recientes" ni "por afinidad": es el top del mercado abierto por
        // score, y la afinidad es una dimensión de seis que además suele estar
        // desactivada. «Encajan con tu perfil» es el perfil de scoring entero
        // (sus pesos), como dicen el pie del Radar y `console-spaces.ts`.
        description: "Las licitaciones abiertas que mejor encajan con tu perfil.",
        usesGlobalFilters: false,
        globalFilterKeys: ["tecnologia"],
        singleValueFilterKeys: ["tecnologia"],
      },
    ],
  },
  {
    label: "Oportunidades",
    pages: [
      {
        label: "Oportunidades",
        slug: "oportunidades",
        description: "Las licitaciones que persigue tu equipo: decisión, responsables, oferta y resultado.",
        usesGlobalFilters: false,
      },
    ],
  },
  {
    label: "Organización",
    pages: [
      {
        label: "Equipo",
        slug: "equipo",
        description: "Quién está en tu organización y qué puede hacer.",
        usesGlobalFilters: false,
      },
    ],
  },
  {
    label: "Inicio",
    pages: [
      {
        label: "Resumen",
        slug: "resumen",
        // Describía «top licitaciones» —un panel que la pantalla no tiene desde
        // hace dos rediseños, servido por `/analytics/resumen/top`, que sigue
        // vivo en el backend sin un solo consumidor. La ficha ahora enumera lo
        // que se pinta de verdad, en el orden en que se pinta.
        description:
          "Tus compromisos del día, lo que exige atención en el mercado abierto y las publicaciones del ámbito.",
      },
    ],
  },
  {
    label: "Licitaciones",
    pages: [
      {
        label: "Detalle",
        slug: "detalle",
        description: "Todas las licitaciones, con filtros y exportación a Excel o CSV.",
        // Consume `GET /licitaciones`, que sí filtra por ellos (F1.1).
        optInFilterKeys: ["procedimiento", "provincia", "importe_max"],
      },
    ],
  },
  {
    label: "Tendencias",
    pages: [
      {
        label: "Tendencias",
        slug: "tendencias",
        description: "Cómo evolucionan cada mes las publicaciones y los importes.",
      },
      {
        label: "Tendencias CPV",
        slug: "tendencias-cpv",
        description: "Importes por CPV a lo largo del tiempo, con su previsión.",
      },
      {
        label: "Calendario",
        slug: "calendario",
        description: "Qué semanas y qué días del año se publica más.",
      },
    ],
  },
  {
    label: "Mercado",
    pages: [
      {
        label: "Órganos",
        slug: "organos",
        description: "Qué órganos contratan más y qué tiene cada uno en marcha.",
      },
      {
        label: "Geografía",
        slug: "geografia",
        description: "Dónde se licita: por comunidad autónoma y por importe.",
      },
      {
        label: "Tecnologías",
        slug: "tecnologias",
        description: "Qué tecnologías piden las licitaciones (SAP, Oracle, Salesforce…) y cómo evolucionan.",
      },
      {
        label: "Proyectos y módulos",
        slug: "proyectos-modulos",
        description: "Qué se licita por familia tecnológica (ERP, CRM, cloud, ciberseguridad…), con los módulos de SAP dentro de ERP.",
      },
      {
        label: "Clusters",
        slug: "clusters",
        description: "Licitaciones parecidas agrupadas, para ver patrones y nichos de mercado.",
      },
      {
        // Reestructura 2026-09-20: `/renovaciones` la absorbe Mercado
        // (`?vista=renovaciones`), no la Agenda. Su contrato de filtros no
        // cambia: sólo aplica tecnología.
        label: "Renovaciones",
        slug: "renovaciones",
        description:
          // «Pipeline comercial» describía la vista cuando vivía en Mi Pipeline;
          // hoy es un corte de mercado sobre contratos de cualquier
          // adjudicatario, y lo tuyo sólo se marca.
          "Contratos de cualquier adjudicatario que vencen pronto: cartera en juego por empresa y riesgo de cambio.",
        usesGlobalFilters: false,
        globalFilterKeys: ["tecnologia"],
      },
    ],
  },
  {
    label: "Competencia",
    pages: [
      {
        label: "Competidores",
        slug: "competidores",
        description: "Quién gana, con qué cuota y frente a quién.",
      },
      {
        label: "Empresas",
        slug: "empresas",
        description: "Fichas de empresa: identidad, alias, seguimiento y alias por revisar.",
        usesGlobalFilters: false,
      },
      {
        label: "UTEs",
        slug: "utes",
        description: "Uniones temporales de empresas: quién se alía con quién y qué ganan.",
      },
    ],
  },
  {
    // Hasta 2026-09-20 la sección se llamaba «Mi Pipeline» y agrupaba también
    // `/renovaciones`; el espacio pasó a llamarse «Agenda» (slug `mi-pipeline`
    // intacto) y las renovaciones son hoy una vista de Mercado.
    label: "Agenda",
    pages: [
      {
        label: "Agenda",
        slug: "pipeline-alertas",
        description: "Lo que vence pronto: oportunidades con plazo, señales sin triar y renovaciones.",
        usesGlobalFilters: false,
        globalFilterKeys: ["tecnologia", "ccaa"],
        singleValueFilterKeys: ["tecnologia", "ccaa"],
      },
      {
        label: "Mi Watchlist",
        slug: "mi-watchlist",
        description: "Avisos de las licitaciones que cumplen tus reglas.",
        usesGlobalFilters: false,
      },
      {
        label: "Mi perfil",
        slug: "mi-perfil",
        description: "Qué te interesa y cuánto pesa cada criterio en la puntuación.",
        usesGlobalFilters: false,
      },
    ],
  },
  {
    label: "Investigador",
    pages: [
      {
        label: "Investigador",
        slug: "investigador",
        description: "Pregunta o busca dentro de las licitaciones y sus pliegos.",
      },
    ],
  },
  {
    label: "Ops",
    pages: [
      {
        label: "Observabilidad",
        slug: "observabilidad",
        description: "Rendimiento, registros de la ingesta y estado de cada paso.",
        usesGlobalFilters: false,
      },
      {
        label: "Calidad de datos",
        slug: "calidad-datos",
        description: "Qué campos faltan, cuánto hace de la última ingesta y qué ha fallado.",
        usesGlobalFilters: false,
      },
    ],
  },
  {
    label: "Administración",
    adminOnly: true,
    pages: [
      {
        label: "Administración",
        slug: "administracion",
        description: "Usuarios, claves de API y la cola de tareas fallidas.",
        usesGlobalFilters: false,
      },
      {
        label: "Feature flags",
        slug: "feature-flags",
        description: "Activar y desactivar funciones, también para una parte de los usuarios.",
        usesGlobalFilters: false,
      },
      {
        label: "Active learning",
        slug: "active-learning",
        description: "Etiquetar a mano las licitaciones que el modelo no sabe clasificar.",
        usesGlobalFilters: false,
      },
    ],
  },
];

/**
 * Flat list of all pages for quick lookup.
 */
export const ALL_PAGES = SECTIONS.flatMap((s) =>
  s.pages.map((p) => ({ ...p, section: s.label })),
);

/**
 * Find a page by its slug.
 */
export function findPage(slug: string) {
  return ALL_PAGES.find((p) => p.slug === slug);
}

/**
 * Página heredada de la que una vista toma su contrato: la ruta que absorbe, o
 * —si es la vista de un espacio retirado por entero que no absorbía ruta
 * propia, como la cola de revisión de Empresas— la de ese espacio.
 */
function paginaDeVista(slug: string, vista: string): NavPage | undefined {
  const view = SPACE_VIEWS[slug]?.find((candidata) => candidata.key === vista);
  if (!view) return undefined;
  if (view.from) return findPage(view.from);
  const absorbido = ESPACIOS_ABSORBIDOS.find(
    (candidato) => candidato.en === slug && Object.values(candidato.vistas).includes(vista),
  );
  return absorbido ? findPage(absorbido.slug) : undefined;
}

/**
 * Páginas heredadas que un espacio de la consola absorbió (`lib/space-views.ts`).
 *
 * Un espacio no declara su contrato de filtros a mano: lo hereda de las rutas
 * que agrupa. Si ninguna de ellas consumía el ámbito —el caso de Ops y Admin—
 * el espacio tampoco lo consume, y la barra de ámbito no aparece fingiendo que
 * filtra algo.
 *
 * Con `vista`, manda la de esa vista si tiene página propia: la unión del
 * espacio ofrecía en Mercado › Renovaciones los seis controles cuando aplica
 * uno, y en Competencia › Empresas un ámbito que el maestro no lee. Sin vista,
 * o con una que no hereda ninguna página, la unión de siempre.
 */
function absorbedPages(slug: string, vista?: string | null): NavPage[] {
  const views = SPACE_VIEWS[slug];
  if (!views) return [];
  const propia = vista ? paginaDeVista(slug, vista) : undefined;
  if (propia) return [propia];
  const pages: NavPage[] = [];
  for (const view of views) {
    const page = view.from ? findPage(view.from) : undefined;
    if (page) pages.push(page);
  }
  return pages;
}

/**
 * Whether the page at `pathname` consumes the global filter state.
 * Rutas desconocidas devuelven `true` (comportamiento histórico). `vista` es
 * el `?vista=` de un espacio: ver `absorbedPages`.
 */
export function pathUsesGlobalFilters(pathname: string, vista?: string | null): boolean {
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const page = findPage(slug);
  if (page) return page.usesGlobalFilters !== false;

  const absorbed = absorbedPages(slug, vista);
  // Unión: basta con que una de las vistas del espacio use el ámbito para que
  // el espacio lo use. Si el espacio no agrupa nada conocido, se mantiene el
  // comportamiento histórico de las rutas desconocidas.
  if (absorbed.length) return absorbed.some((item) => item.usesGlobalFilters !== false);
  return true;
}

/**
 * Subconjunto de filtros globales que la página aplica, o `null` cuando la
 * página consume todos (comportamiento por defecto). La GlobalFilterBar usa
 * esto para renderizar solo los controles relevantes.
 */
export function pageGlobalFilterKeys(pathname: string, vista?: string | null): GlobalFilterKey[] | null {
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const page = findPage(slug);
  if (page) return page.globalFilterKeys ?? null;

  const absorbed = absorbedPages(slug, vista);
  if (!absorbed.length) return null;
  // Si alguna vista del espacio consume todos los filtros, el espacio también:
  // recortar la barra al subconjunto de otra vista escondería un control que
  // esa vista sí aplica.
  if (absorbed.some((item) => !item.globalFilterKeys)) return null;
  const union = new Set<GlobalFilterKey>();
  for (const item of absorbed) for (const key of item.globalFilterKeys ?? []) union.add(key);
  return [...union];
}

/**
 * Filtros opt-in ({@link FILTROS_OPT_IN}) que la página aplica. Un espacio
 * hereda la unión de las rutas que absorbe: basta con que una vista los
 * aplique para ofrecerlos.
 */
export function pageOptInFilterKeys(pathname: string, vista?: string | null): GlobalFilterKey[] {
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const page = findPage(slug);
  if (page) return page.optInFilterKeys ?? [];
  const union = new Set<GlobalFilterKey>();
  for (const item of absorbedPages(slug, vista)) for (const key of item.optInFilterKeys ?? []) union.add(key);
  return [...union];
}

/**
 * Subconjunto de `pageGlobalFilterKeys` cuya selección reemplaza el valor
 * anterior en vez de acumularse (ver `NavPage.singleValueFilterKeys`).
 */
export function pageSingleValueFilterKeys(pathname: string): GlobalFilterKey[] {
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const page = findPage(slug);
  return page?.singleValueFilterKeys ?? [];
}
