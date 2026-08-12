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
import { SPACE_VIEWS } from "@/lib/space-views";

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
    icon: RadioTower,
    pages: [
      {
        label: "Radar",
        slug: "radar",
        // Ni "recientes" ni "por afinidad": es el top del mercado abierto por
        // score, y la afinidad es una dimensión de seis que además suele estar
        // desactivada. La descripción prometía el ranking que el P0 del
        // UX_AUDIT corrigió en la página y que aquí quedó sin actualizar.
        description: "Top del mercado abierto por potencial comercial.",
        icon: RadioTower,
        usesGlobalFilters: false,
        globalFilterKeys: ["tecnologia"],
        singleValueFilterKeys: ["tecnologia"],
      },
    ],
  },
  {
    label: "Oportunidades",
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
 * Subconjunto de `pageGlobalFilterKeys` cuya selección reemplaza el valor
 * anterior en vez de acumularse (ver `NavPage.singleValueFilterKeys`).
 */
export function pageSingleValueFilterKeys(pathname: string): GlobalFilterKey[] {
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const page = findPage(slug);
  return page?.singleValueFilterKeys ?? [];
}
