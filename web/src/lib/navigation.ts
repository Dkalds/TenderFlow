/**
 * Navigation configuration.
 *
 * Single source of truth for the frontend navigation tree.
 */

import {
  BarChart3,
  Briefcase,
  Building2,
  Calendar,
  CalendarClock,
  Eye,
  Flag,
  Globe,
  GraduationCap,
  Handshake,
  type LucideIcon,
  LayoutDashboard,
  ListChecks,
  Map,
  Puzzle,
  RadioTower,
  Search,
  Settings,
  Shield,
  Sparkles,
  Star,
  Target,
  TrendingUp,
  Trophy,
  Users,
  Wrench,
} from "lucide-react";

export type GlobalFilterKey =
  | "q"
  | "fecha"
  | "ccaa"
  | "tecnologia"
  | "estado"
  | "importe";

export interface NavPage {
  label: string;
  slug: string;
  description: string;
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
}

export interface NavSection {
  label: string;
  icon: LucideIcon;
  pages: NavPage[];
  adminOnly?: boolean;
  /**
   * Espacio de producto al que pertenece la sección, **declarado**.
   *
   * Antes se infería por descarte ("si no es Radar ni Oportunidades, es
   * Mercado"), de modo que el breadcrumb anunciaba "Mercado › Administración" y
   * "Mercado › Calidad de Datos". Ops, Admin y Mi Pipeline no son análisis de
   * mercado: se quedan sin espacio y el breadcrumb arranca en su sección.
   */
  space?: ProductSpace["label"];
}

/**
 * The product's primary mental model.  Legacy analytical routes stay in
 * `SECTIONS` beneath Mercado so bookmarks and the existing exploration tools
 * remain available during the gradual migration.
 */
export interface ProductSpace {
  label: "Radar" | "Oportunidades" | "Mercado";
  slug: string;
  description: string;
  icon: LucideIcon;
}

export const PRODUCT_SPACES: ProductSpace[] = [
  {
    label: "Radar",
    slug: "radar",
    description: "Descubrimiento personalizado y acción directa.",
    icon: RadioTower,
  },
  {
    label: "Oportunidades",
    slug: "oportunidades",
    description: "Decisiones, equipo, oferta y resultado.",
    icon: Briefcase,
  },
  {
    label: "Mercado",
    slug: "resumen",
    description: "Consulta analítica con alcance explícito.",
    icon: Globe,
  },
];

export const SECTIONS: NavSection[] = [
  {
    label: "Radar",
    space: "Radar",
    icon: RadioTower,
    pages: [
      {
        label: "Radar",
        slug: "radar",
        description: "Señales recientes del mercado, ordenadas por afinidad.",
        icon: RadioTower,
        usesGlobalFilters: false,
        globalFilterKeys: ["tecnologia"],
        singleValueFilterKeys: ["tecnologia"],
      },
    ],
  },
  {
    label: "Oportunidades",
    space: "Oportunidades",
    icon: Briefcase,
    pages: [
      {
        label: "Oportunidades",
        slug: "oportunidades",
        description: "Espacio operativo de decisiones, responsables, ofertas y resultados.",
        icon: Briefcase,
        usesGlobalFilters: false,
      },
    ],
  },
  {
    label: "Organización",
    icon: Users,
    pages: [
      {
        label: "Equipo",
        slug: "equipo",
        description: "Organizaciones compartidas, miembros y roles del equipo.",
        icon: Users,
        usesGlobalFilters: false,
      },
    ],
  },
  {
    label: "Inicio",
    space: "Mercado",
    icon: LayoutDashboard,
    pages: [
      {
        label: "Resumen",
        slug: "resumen",
        description:
          "Top licitaciones, distribución por estado y salud competitiva del mercado.",
        icon: LayoutDashboard,
      },
    ],
  },
  {
    label: "Licitaciones",
    space: "Mercado",
    icon: Search,
    pages: [
      {
        label: "Detalle",
        slug: "detalle",
        description:
          "Tabla completa con todos los campos y exportación a Excel/CSV.",
        icon: Search,
      },
    ],
  },
  {
    label: "Tendencias",
    space: "Mercado",
    icon: TrendingUp,
    pages: [
      {
        label: "Tendencias",
        slug: "tendencias",
        description:
          "Evolución mensual de publicaciones e importes, heatmap y distribución.",
        icon: TrendingUp,
      },
      {
        label: "Tendencias CPV",
        slug: "tendencias-cpv",
        description:
          "Serie temporal de importes por CPV con predicción ARIMA.",
        icon: BarChart3,
      },
      {
        label: "Calendario",
        slug: "calendario",
        description: "Heatmap de publicaciones por semana y día del año.",
        icon: Calendar,
      },
    ],
  },
  {
    label: "Mercado",
    space: "Mercado",
    icon: Globe,
    pages: [
      {
        label: "Órganos",
        slug: "organos",
        description:
          "Ranking de órganos contratantes, treemap y análisis de pipeline individual.",
        icon: Building2,
      },
      {
        label: "Geografía",
        slug: "geografia",
        description:
          "Distribución geográfica por comunidad autónoma e importe acumulado.",
        icon: Map,
      },
      {
        label: "Tecnologías",
        slug: "tecnologias",
        description:
          "Distribución, evolución y cruces por tecnología detectada (SAP, Oracle, Salesforce…).",
        icon: Wrench,
      },
      {
        label: "Proyectos y Módulos",
        slug: "proyectos-modulos",
        description:
          "Desglose por tipo de proyecto y módulo SAP detectado.",
        icon: Puzzle,
      },
      {
        label: "Clusters",
        slug: "clusters",
        description:
          "Agrupaciones semánticas de licitaciones para detectar patrones y nichos de mercado.",
        icon: Target,
      },
    ],
  },
  {
    label: "Competencia",
    space: "Mercado",
    icon: Trophy,
    pages: [
      {
        label: "Competidores",
        slug: "competidores",
        description:
          "Empresas adjudicatarias, cuota de mercado y análisis comparativo.",
        icon: Trophy,
      },
      {
        label: "Empresas",
        slug: "empresas",
        description:
          "Maestro de empresas canónicas: buscador, perfil competitivo, alias y vigilancia.",
        icon: Briefcase,
        usesGlobalFilters: false,
      },
      {
        label: "UTEs",
        slug: "utes",
        description:
          "Análisis de Uniones Temporales de Empresas: alianzas, estructura y contratos ganados.",
        icon: Handshake,
      },
    ],
  },
  {
    label: "Mi Pipeline",
    icon: ListChecks,
    pages: [
      {
        label: "Pipeline & Alertas",
        slug: "pipeline-alertas",
        description:
          "Licitaciones en plazo, predicciones y alertas de vencimiento.",
        icon: ListChecks,
      },
      {
        label: "Renovaciones",
        slug: "renovaciones",
        description:
          "Contratos que vencen próximamente: cartera en juego por empresa y pipeline comercial.",
        icon: CalendarClock,
        usesGlobalFilters: false,
        globalFilterKeys: ["tecnologia"],
      },
      {
        label: "Mi Watchlist",
        slug: "mi-watchlist",
        description:
          "Reglas de seguimiento personalizadas por CPV, keyword e importe.",
        icon: Star,
        usesGlobalFilters: false,
      },
      {
        label: "Mi Perfil de Scoring",
        slug: "mi-perfil",
        description:
          "Personaliza los pesos de scoring, keywords de afinidad y rango de importe.",
        icon: Settings,
        usesGlobalFilters: false,
      },
    ],
  },
  {
    label: "Investigador",
    space: "Mercado",
    icon: Sparkles,
    pages: [
      {
        label: "Investigador",
        slug: "investigador",
        description:
          "Búsqueda semántica RAG sobre el corpus de licitaciones.",
        icon: Search,
      },
    ],
  },
  {
    label: "Ops",
    icon: Eye,
    pages: [
      {
        label: "Observabilidad",
        slug: "observabilidad",
        description:
          "Métricas de rendimiento, logs de scraping y estado del pipeline.",
        icon: BarChart3,
        usesGlobalFilters: false,
      },
      {
        label: "Calidad de Datos",
        slug: "calidad-datos",
        description:
          "Completitud del dataset, frescura del scraping, tasa de errores y DLQ.",
        icon: Shield,
        usesGlobalFilters: false,
      },
    ],
  },
  {
    label: "Admin",
    icon: Settings,
    adminOnly: true,
    pages: [
      {
        label: "Administración",
        slug: "administracion",
        description:
          "Gestión de DLQ, usuarios y API keys. Solo accesible para administradores.",
        icon: Settings,
        usesGlobalFilters: false,
      },
      {
        label: "Feature Flags",
        slug: "feature-flags",
        description:
          "Activar y desactivar funcionalidades en tiempo real con despliegue gradual.",
        icon: Flag,
        usesGlobalFilters: false,
      },
      {
        label: "Active Learning",
        slug: "active-learning",
        description:
          "Etiquetado humano de licitaciones en la zona de incertidumbre del modelo.",
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
 * Find the section that contains a page slug.
 */
export function findSection(slug: string) {
  return SECTIONS.find((s) => s.pages.some((p) => p.slug === slug));
}

/**
 * Espacio de producto al que pertenece una ruta, según lo declarado en su
 * sección (`NavSection.space`).
 *
 * Devuelve `undefined` para las secciones que no viven bajo ningún espacio
 * (Mi Pipeline, Ops, Admin). Antes esta función devolvía `Mercado` para
 * cualquier ruta conocida que no fuese radar/oportunidades, y de ahí salían
 * breadcrumbs falsos como "Mercado › Administración".
 */
export function findProductSpace(slug: string): ProductSpace | undefined {
  const cleanSlug = slug.replace(/^\//, "").split("/")[0];
  const sectionSpace = findSection(cleanSlug)?.space;
  return sectionSpace
    ? PRODUCT_SPACES.find((space) => space.label === sectionSpace)
    : undefined;
}

/**
 * Whether the page at `pathname` consumes the global filter state.
 * Rutas desconocidas devuelven `true` (comportamiento histórico).
 */
export function pathUsesGlobalFilters(pathname: string): boolean {
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const page = findPage(slug);
  return page ? page.usesGlobalFilters !== false : true;
}

/**
 * Subconjunto de filtros globales que la página aplica, o `null` cuando la
 * página consume todos (comportamiento por defecto). La GlobalFilterBar usa
 * esto para renderizar solo los controles relevantes.
 */
export function pageGlobalFilterKeys(pathname: string): GlobalFilterKey[] | null {
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const page = findPage(slug);
  return page?.globalFilterKeys ?? null;
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
