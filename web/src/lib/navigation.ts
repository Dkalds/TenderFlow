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

import {
  BarChart3,
  Calendar,
  Flag,
  GraduationCap,
  type LucideIcon,
  Map,
  Puzzle,
  Shield,
  Target,
  TrendingUp,
  Wrench,
} from "lucide-react";
import { ICONO_ADMIN, ICONO_CONCEPTO, ICONO_ENTIDAD, ICONO_ESPACIO } from "@/lib/iconos";
import { SPACE_VIEWS } from "@/lib/space-views";

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
   * Icono de la página. Un espacio usa el suyo (`ICONO_ESPACIO`) y una entidad
   * el de la entidad (`ICONO_ENTIDAD`): el mismo glifo que en el rail y la
   * paleta. Solo lo pintan hoy los atajos del Resumen.
   */
  icon: LucideIcon;
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
  icon: LucideIcon;
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
    icon: ICONO_ESPACIO.radar,
    pages: [
      {
        label: "Radar",
        slug: "radar",
        // Ni "recientes" ni "por afinidad": es el top del mercado abierto por
        // score, y la afinidad es una dimensión de seis que además suele estar
        // desactivada. La descripción prometía el ranking que el P0 del
        // UX_AUDIT corrigió en la página y que aquí quedó sin actualizar.
        description: "Top del mercado abierto por potencial comercial.",
        icon: ICONO_ESPACIO.radar,
        usesGlobalFilters: false,
        globalFilterKeys: ["tecnologia"],
        singleValueFilterKeys: ["tecnologia"],
      },
    ],
  },
  {
    label: "Oportunidades",
    icon: ICONO_ESPACIO.oportunidades,
    pages: [
      {
        label: "Oportunidades",
        slug: "oportunidades",
        description: "Las licitaciones que persigue tu equipo: decisión, responsables, oferta y resultado.",
        icon: ICONO_ESPACIO.oportunidades,
        usesGlobalFilters: false,
      },
    ],
  },
  {
    label: "Organización",
    icon: ICONO_ESPACIO.equipo,
    pages: [
      {
        label: "Equipo",
        slug: "equipo",
        description: "Quién está en tu organización y qué puede hacer.",
        icon: ICONO_ESPACIO.equipo,
        usesGlobalFilters: false,
      },
    ],
  },
  {
    label: "Inicio",
    icon: ICONO_ESPACIO.resumen,
    pages: [
      {
        label: "Resumen",
        slug: "resumen",
        // Describía «top licitaciones» —un panel que la pantalla no tiene desde
        // hace dos rediseños, servido por `/analytics/resumen/top`, que sigue
        // vivo en el backend sin un solo consumidor. La ficha ahora enumera lo
        // que se pinta de verdad, en el orden en que se pinta.
        description:
          "Tus compromisos del día, lo que exige atención en el mercado abierto y la salud competitiva del ámbito.",
        icon: ICONO_ESPACIO.resumen,
      },
    ],
  },
  {
    label: "Licitaciones",
    icon: ICONO_ESPACIO.detalle,
    pages: [
      {
        label: "Detalle",
        slug: "detalle",
        description: "Todas las licitaciones, con filtros y exportación a Excel o CSV.",
        icon: ICONO_ESPACIO.detalle,
        // Consume `GET /licitaciones`, que sí filtra por ellos (F1.1).
        optInFilterKeys: ["procedimiento", "provincia", "importe_max"],
      },
    ],
  },
  {
    label: "Tendencias",
    icon: TrendingUp,
    pages: [
      {
        label: "Tendencias",
        slug: "tendencias",
        description: "Cómo evolucionan cada mes las publicaciones y los importes.",
        icon: TrendingUp,
      },
      {
        label: "Tendencias CPV",
        slug: "tendencias-cpv",
        description: "Importes por CPV a lo largo del tiempo, con su previsión.",
        icon: BarChart3,
      },
      {
        label: "Calendario",
        slug: "calendario",
        description: "Qué semanas y qué días del año se publica más.",
        icon: Calendar,
      },
    ],
  },
  {
    label: "Mercado",
    icon: ICONO_ESPACIO.mercado,
    pages: [
      {
        label: "Órganos",
        slug: "organos",
        description: "Qué órganos contratan más y qué tiene cada uno en marcha.",
        icon: ICONO_ENTIDAD.organo,
      },
      {
        label: "Geografía",
        slug: "geografia",
        description: "Dónde se licita: por comunidad autónoma y por importe.",
        icon: Map,
      },
      {
        label: "Tecnologías",
        slug: "tecnologias",
        description: "Qué tecnologías piden las licitaciones (SAP, Oracle, Salesforce…) y cómo evolucionan.",
        icon: Wrench,
      },
      {
        label: "Proyectos y módulos",
        slug: "proyectos-modulos",
        description: "Por tipo de proyecto y por módulo de SAP.",
        icon: Puzzle,
      },
      {
        label: "Clusters",
        slug: "clusters",
        description: "Licitaciones parecidas agrupadas, para ver patrones y nichos de mercado.",
        icon: Target,
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
        icon: ICONO_CONCEPTO.plazo,
        usesGlobalFilters: false,
        globalFilterKeys: ["tecnologia"],
      },
    ],
  },
  {
    label: "Competencia",
    icon: ICONO_ESPACIO.competencia,
    pages: [
      {
        label: "Competidores",
        slug: "competidores",
        description: "Quién gana, con qué cuota y frente a quién.",
        icon: ICONO_ESPACIO.competencia,
      },
      {
        label: "Empresas",
        slug: "empresas",
        description: "Fichas de empresa: identidad, alias, seguimiento y alias por revisar.",
        icon: ICONO_ENTIDAD.empresa,
        usesGlobalFilters: false,
      },
      {
        label: "UTEs",
        slug: "utes",
        description: "Uniones temporales de empresas: quién se alía con quién y qué ganan.",
        icon: ICONO_ENTIDAD.ute,
      },
    ],
  },
  {
    // Hasta 2026-09-20 la sección se llamaba «Mi Pipeline» y agrupaba también
    // `/renovaciones`; el espacio pasó a llamarse «Agenda» (slug `mi-pipeline`
    // intacto) y las renovaciones son hoy una vista de Mercado.
    label: "Agenda",
    icon: ICONO_ESPACIO["mi-pipeline"],
    pages: [
      {
        label: "Agenda",
        slug: "pipeline-alertas",
        description: "Lo que vence pronto: oportunidades con plazo, señales sin triar y renovaciones.",
        icon: ICONO_ESPACIO["mi-pipeline"],
        usesGlobalFilters: false,
        globalFilterKeys: ["tecnologia", "ccaa"],
        singleValueFilterKeys: ["tecnologia", "ccaa"],
      },
      {
        label: "Mi Watchlist",
        slug: "mi-watchlist",
        description: "Avisos de las licitaciones que cumplen tus reglas.",
        icon: ICONO_ESPACIO["mi-watchlist"],
        usesGlobalFilters: false,
      },
      {
        label: "Mi perfil",
        slug: "mi-perfil",
        description: "Qué te interesa y cuánto pesa cada criterio en la puntuación.",
        icon: ICONO_ESPACIO["mi-perfil"],
        usesGlobalFilters: false,
      },
    ],
  },
  {
    label: "Investigador",
    icon: ICONO_ESPACIO.investigador,
    pages: [
      {
        label: "Investigador",
        slug: "investigador",
        description: "Pregunta o busca dentro de las licitaciones y sus pliegos.",
        icon: ICONO_ESPACIO.investigador,
      },
    ],
  },
  {
    label: "Ops",
    icon: ICONO_ESPACIO.ops,
    pages: [
      {
        label: "Observabilidad",
        slug: "observabilidad",
        description: "Rendimiento, registros de la ingesta y estado de cada paso.",
        icon: BarChart3,
        usesGlobalFilters: false,
      },
      {
        label: "Calidad de datos",
        slug: "calidad-datos",
        description: "Qué campos faltan, cuánto hace de la última ingesta y qué ha fallado.",
        icon: Shield,
        usesGlobalFilters: false,
      },
    ],
  },
  {
    label: "Admin",
    icon: ICONO_ADMIN,
    adminOnly: true,
    pages: [
      {
        label: "Administración",
        slug: "administracion",
        description: "Usuarios, claves de API y la cola de tareas fallidas.",
        icon: ICONO_ADMIN,
        usesGlobalFilters: false,
      },
      {
        label: "Feature flags",
        slug: "feature-flags",
        description: "Activar y desactivar funciones, también para una parte de los usuarios.",
        icon: Flag,
        usesGlobalFilters: false,
      },
      {
        label: "Active learning",
        slug: "active-learning",
        description: "Etiquetar a mano las licitaciones que el modelo no sabe clasificar.",
        icon: GraduationCap,
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
 * Páginas heredadas que un espacio de la consola absorbió (`lib/space-views.ts`).
 *
 * Un espacio no declara su contrato de filtros a mano: lo hereda de las rutas
 * que agrupa. Si ninguna de ellas consumía el ámbito —el caso de Ops y Admin—
 * el espacio tampoco lo consume, y la barra de ámbito no aparece fingiendo que
 * filtra algo.
 */
function absorbedPages(slug: string): NavPage[] {
  const views = SPACE_VIEWS[slug];
  if (!views) return [];
  const pages: NavPage[] = [];
  for (const view of views) {
    const page = view.from ? findPage(view.from) : undefined;
    if (page) pages.push(page);
  }
  return pages;
}

/**
 * Whether the page at `pathname` consumes the global filter state.
 * Rutas desconocidas devuelven `true` (comportamiento histórico).
 */
export function pathUsesGlobalFilters(pathname: string): boolean {
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const page = findPage(slug);
  if (page) return page.usesGlobalFilters !== false;

  const absorbed = absorbedPages(slug);
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
export function pageGlobalFilterKeys(pathname: string): GlobalFilterKey[] | null {
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const page = findPage(slug);
  if (page) return page.globalFilterKeys ?? null;

  const absorbed = absorbedPages(slug);
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
export function pageOptInFilterKeys(pathname: string): GlobalFilterKey[] {
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const page = findPage(slug);
  if (page) return page.optInFilterKeys ?? [];
  const union = new Set<GlobalFilterKey>();
  for (const item of absorbedPages(slug)) for (const key of item.optInFilterKeys ?? []) union.add(key);
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
