/**
 * Mapa de espacios de la consola.
 *
 * El rediseño (ver `docs/redesign/README.md`) consolida las 25 rutas del
 * dashboard en 14 espacios navegables. Este módulo es la única fuente de
 * verdad de esa consolidación y gobierna tres cosas a la vez:
 *
 * 1. El rail de 56px (`components/layout/console-rail.tsx`).
 * 2. Qué rutas visten el chrome nuevo (rail + barra de ámbito) y cuáles siguen
 *    con el chrome heredado (breadcrumb + pestañas + barra de filtros clásica),
 *    mientras se migran por lotes.
 * 3. Los redirects de las rutas absorbidas hacia la vista equivalente del
 *    espacio, para que ningún enlace guardado se rompa (`LEGACY_REDIRECTS`).
 *
 * Regla dura del proyecto: consolidar nunca puede eliminar funcionalidad. Una
 * ruta absorbida se convierte en `?vista=` del espacio, jamás desaparece.
 */

import {
  Binoculars,
  Briefcase,
  Building2,
  type LucideIcon,
  LayoutDashboard,
  ListChecks,
  Network,
  RadioTower,
  Settings2,
  ShieldCheck,
  Sparkles,
  Star,
  Table2,
  Trophy,
  Users,
} from "lucide-react";
import { BUILT_SPACE_ROUTES, SPACE_VIEWS, type SpaceView } from "@/lib/space-views";

/** Agrupación visual del rail. Separadores, no navegación. */
export type ConsoleGroup = "trabajo" | "analisis" | "personal" | "organizacion";

export interface ConsoleSpace {
  /** Identificador estable, usado en tests y telemetría. */
  key: string;
  label: string;
  /** Etiqueta de 3 letras bajo el icono del rail (mono, 8px). */
  short: string;
  /** Ruta raíz del espacio, sin barra inicial. */
  slug: string;
  description: string;
  icon: LucideIcon;
  group: ConsoleGroup;
  /**
   * Vistas del espacio, tomadas de `lib/space-views.ts` (tabla compartida con
   * `next.config.ts`). La primera es la de entrada (`?vista=` ausente); una
   * vista con `from` absorbe esa ruta heredada.
   */
  views?: SpaceView[];
}

export const CONSOLE_SPACES: ConsoleSpace[] = [
  {
    key: "resumen",
    label: "Resumen",
    short: "RES",
    slug: "resumen",
    description: "La entrada: qué ha cambiado y qué exige atención hoy.",
    icon: LayoutDashboard,
    group: "trabajo",
  },
  {
    key: "radar",
    label: "Radar",
    short: "RAD",
    slug: "radar",
    description: "Consola de decisión diaria: seguir, descartar, abrir.",
    icon: RadioTower,
    group: "trabajo",
  },
  {
    key: "detalle",
    label: "Detalle",
    short: "DET",
    slug: "detalle",
    description: "Tabla de trabajo con inspector en el mismo plano.",
    icon: Table2,
    group: "trabajo",
  },
  {
    key: "oportunidades",
    label: "Oportunidades",
    short: "OPS",
    slug: "oportunidades",
    description: "Espacio de ejecución: decisión, pliego y precio.",
    icon: Briefcase,
    group: "trabajo",
  },
  {
    key: "mercado",
    label: "Mercado",
    short: "MKT",
    slug: "mercado",
    description: "Ocho cortes del mismo dataset sobre una superficie.",
    icon: Binoculars,
    group: "analisis",
    views: SPACE_VIEWS.mercado,
  },
  {
    key: "competencia",
    label: "Competencia",
    short: "CMP",
    slug: "competencia",
    description: "Tabla de competidores y nueve cortes con pestañas.",
    icon: Trophy,
    group: "analisis",
    views: SPACE_VIEWS.competencia,
  },
  {
    key: "relaciones",
    label: "Relaciones",
    short: "REL",
    slug: "relaciones",
    description: "Estructura de mercado: concentración, grafos y partners.",
    icon: Network,
    group: "analisis",
    views: SPACE_VIEWS.relaciones,
  },
  {
    key: "investigador",
    label: "Investigador",
    short: "IA",
    slug: "investigador",
    description: "Búsqueda semántica y conversación sobre el corpus.",
    icon: Sparkles,
    group: "analisis",
  },
  {
    key: "mi-pipeline",
    label: "Mi Pipeline",
    short: "PIP",
    slug: "mi-pipeline",
    description: "Licitaciones en plazo, alertas y renovaciones.",
    icon: ListChecks,
    group: "personal",
    views: SPACE_VIEWS["mi-pipeline"],
  },
  {
    key: "mi-watchlist",
    label: "Mi Watchlist",
    short: "WLS",
    slug: "mi-watchlist",
    description: "Reglas de seguimiento por CPV, keyword e importe.",
    icon: Star,
    group: "personal",
  },
  {
    key: "mi-perfil",
    label: "Mi perfil",
    short: "PRF",
    slug: "mi-perfil",
    description: "Pesos de scoring, keywords y rango de importe.",
    icon: Settings2,
    group: "personal",
  },
  {
    key: "empresas",
    label: "Empresas",
    short: "EMP",
    slug: "empresas",
    description: "Maestro canónico, alias y cola de revisión.",
    icon: Building2,
    group: "organizacion",
  },
  {
    key: "equipo",
    label: "Equipo",
    short: "EQU",
    slug: "equipo",
    description: "Organizaciones, miembros y matriz de permisos.",
    icon: Users,
    group: "organizacion",
  },
  {
    key: "ops",
    label: "Ops y Admin",
    short: "OPX",
    slug: "ops",
    description: "Observabilidad, calidad del dato y administración.",
    icon: ShieldCheck,
    group: "organizacion",
    views: SPACE_VIEWS.ops,
  },
];

/** Espacios que sólo ve un administrador. */
export const ADMIN_ONLY_SPACES = new Set(["ops"]);

export const CONSOLE_GROUP_ORDER: ConsoleGroup[] = [
  "trabajo",
  "analisis",
  "personal",
  "organizacion",
];

/** Primer segmento de una ruta, sin barras ni query. */
export function routeSlug(pathname: string): string {
  return pathname.replace(/^\//, "").split(/[?#]/)[0].split("/")[0];
}

export function findConsoleSpace(pathname: string): ConsoleSpace | undefined {
  const slug = routeSlug(pathname);
  return CONSOLE_SPACES.find((space) => space.slug === slug);
}

/**
 * Rutas de espacio ya construidas, como Set para lookups. La migración está
 * completa (14/14): toda ruta del dashboard es superficie de consola y el
 * cromo heredado (breadcrumb, pestañas, KPI bar) se retiró en 2026-08 —
 * `console-frame.tsx` monta una única superficie sin mirar la ruta.
 */
export const CONSOLE_ROUTES = new Set<string>(BUILT_SPACE_ROUTES);

/** ¿El espacio tiene ya su propia ruta, o sigue viviendo en las heredadas? */
export function isSpaceImplemented(space: ConsoleSpace): boolean {
  return !space.views?.length || CONSOLE_ROUTES.has(space.slug);
}

/**
 * Destino real del espacio hoy: su ruta propia si existe, y si no la primera
 * de las rutas que absorberá. Así el rail nunca enlaza a una ruta inexistente
 * ni deja una pantalla del repo sin forma de llegar a ella.
 */
export function landingHref(space: ConsoleSpace): string {
  if (isSpaceImplemented(space)) return `/${space.slug}`;
  const first = space.views?.find((view) => view.from);
  return first?.from ? `/${first.from}` : `/${space.slug}`;
}

/**
 * Ruta heredada → destino en el espacio que la absorbe. Se consume desde
 * `next.config.ts` (redirects permanentes) y desde la command palette, para
 * que un marcador de `/tendencias-cpv` siga aterrizando en el mismo análisis.
 * Sólo entran las rutas cuyo espacio ya está construido.
 */
export const LEGACY_REDIRECTS: { from: string; to: string }[] = CONSOLE_SPACES.filter(
  isSpaceImplemented,
).flatMap((space) =>
  (space.views ?? [])
    .filter((view): view is Required<SpaceView> => Boolean(view.from))
    .map((view) => ({
      from: `/${view.from}`,
      to: `/${space.slug}?vista=${view.key}`,
    })),
);

/** Espacio que absorbió una ruta heredada, si la absorbió alguno. */
export function spaceAbsorbing(slug: string): { space: ConsoleSpace; view: string } | undefined {
  for (const space of CONSOLE_SPACES) {
    const view = space.views?.find((candidate) => candidate.from === slug);
    if (view) return { space, view: view.key };
  }
  return undefined;
}
