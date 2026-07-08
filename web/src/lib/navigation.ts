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
  Link2,
  ListChecks,
  Map,
  Network,
  Puzzle,
  Search,
  Settings,
  Shield,
  Sparkles,
  Star,
  Target,
  TrendingUp,
  Trophy,
  Wrench,
} from "lucide-react";

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
}

export interface NavSection {
  label: string;
  icon: LucideIcon;
  pages: NavPage[];
  adminOnly?: boolean;
}

export const SECTIONS: NavSection[] = [
  {
    label: "Inicio",
    icon: LayoutDashboard,
    pages: [
      {
        label: "Resumen",
        slug: "resumen",
        description:
          "Top licitaciones, distribucion por estado y salud competitiva del mercado.",
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
          "Tabla completa con todos los campos y exportacion a Excel/CSV.",
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
          "Evolucion mensual de publicaciones e importes, heatmap y distribucion.",
        icon: TrendingUp,
      },
      {
        label: "Tendencias CPV",
        slug: "tendencias-cpv",
        description:
          "Serie temporal de importes por CPV con prediccion ARIMA.",
        icon: BarChart3,
      },
      {
        label: "Calendario",
        slug: "calendario",
        description: "Heatmap de publicaciones por semana/dia del anio.",
        icon: Calendar,
      },
    ],
  },
  {
    label: "Mercado",
    icon: Globe,
    pages: [
      {
        label: "Organos",
        slug: "organos",
        description:
          "Ranking de organos contratantes, treemap y analisis de pipeline individual.",
        icon: Building2,
      },
      {
        label: "Geografia",
        slug: "geografia",
        description:
          "Distribucion geografica por comunidad autonoma e importe acumulado.",
        icon: Map,
      },
      {
        label: "Tecnologias",
        slug: "tecnologias",
        description:
          "Distribucion, evolucion y cruces por tecnologia detectada (SAP, Oracle, Salesforce...).",
        icon: Wrench,
      },
      {
        label: "Proyectos & Modulos",
        slug: "proyectos-modulos",
        description:
          "Desglose por tipo de proyecto y modulo SAP detectado.",
        icon: Puzzle,
      },
      {
        label: "Clusters",
        slug: "clusters",
        description:
          "Agrupaciones semanticas de licitaciones para detectar patrones y nichos de mercado.",
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
          "Empresas adjudicatarias, cuota de mercado y analisis comparativo.",
        icon: Trophy,
      },
      {
        label: "Empresas",
        slug: "empresas",
        description:
          "Maestro de empresas canonicas: buscador, perfil competitivo, aliases y vigilancia.",
        icon: Briefcase,
        usesGlobalFilters: false,
      },
      {
        label: "UTEs",
        slug: "utes",
        description:
          "Analisis de Uniones Temporales de Empresas: alianzas, estructura y contratos ganados.",
        icon: Handshake,
      },
    ],
  },
  {
    label: "Relaciones",
    icon: Network,
    pages: [
      {
        label: "Ecosistema Partners",
        slug: "ecosistema-partners",
        description:
          "Grafo de co-adjudicaciones, ganadores por segmento y buscador de partners.",
        icon: Network,
      },
      {
        label: "Red Organo-Empresa",
        slug: "red-organo-empresa",
        description:
          "Grafo bipartito de relaciones contractuales entre organos contratantes y empresas.",
        icon: Link2,
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
          "Contratos que vencen proximamente: cartera en juego por empresa y pipeline comercial.",
        icon: CalendarClock,
        usesGlobalFilters: false,
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
          "Busqueda semantica RAG sobre el corpus de licitaciones.",
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
          "Metricas de rendimiento, logs de scraping y estado del pipeline.",
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
        label: "Administracion",
        slug: "administracion",
        description:
          "Gestion de DLQ, usuarios y API Keys. Solo accesible para administradores.",
        icon: Settings,
        usesGlobalFilters: false,
      },
      {
        label: "Feature Flags",
        slug: "feature-flags",
        description:
          "Activar/desactivar funcionalidades en tiempo real con rollout gradual.",
        icon: Flag,
        usesGlobalFilters: false,
      },
      {
        label: "Active Learning",
        slug: "active-learning",
        description:
          "Etiquetado humano de licitaciones en zona de incertidumbre del modelo ML.",
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
 * Whether the page at `pathname` consumes the global filter state.
 * Rutas desconocidas devuelven `true` (comportamiento histórico).
 */
export function pathUsesGlobalFilters(pathname: string): boolean {
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const page = findPage(slug);
  return page ? page.usesGlobalFilters !== false : true;
}
