/**
 * Mapa de espacios de la consola.
 *
 * El rediseño (ver `docs/redesign/README.md`) consolida las 25 rutas del
 * dashboard en 13 espacios navegables. Este módulo es la única fuente de
 * verdad de esa consolidación y gobierna tres cosas a la vez:
 *
 * 1. El rail (`components/layout/console-rail.tsx`): icono y nombre de cada
 *    espacio, en castellano y sin abreviar.
 * 2. Qué rutas visten el chrome nuevo (rail + barra de ámbito) y cuáles siguen
 *    con el chrome heredado (breadcrumb + pestañas + barra de filtros clásica),
 *    mientras se migran por lotes.
 * 3. Los redirects de las rutas absorbidas hacia la vista equivalente del
 *    espacio, para que ningún enlace guardado se rompa (`legacyRedirects()`
 *    de `lib/space-views.ts`, que consume `next.config.ts`).
 *
 * Regla dura del proyecto: consolidar nunca puede eliminar funcionalidad. Una
 * ruta absorbida se convierte en `?vista=` del espacio, jamás desaparece.
 */

import type { LucideIcon } from "lucide-react";
import { ICONO_ESPACIO } from "@/lib/iconos";
import { BUILT_SPACE_ROUTES, SPACE_VIEWS, type SpaceView } from "@/lib/space-views";

/** Agrupación visual del rail. Separadores, no navegación. */
export type ConsoleGroup = "trabajo" | "analisis" | "personal" | "organizacion";

export interface ConsoleSpace {
  /** Identificador estable, usado en tests y telemetría. */
  key: string;
  /**
   * Nombre del espacio. Es también la palabra que el rail pinta bajo el icono:
   * sin códigos de tres letras que hubiera que aprenderse (RES, MKT, OPX…), y
   * el nombre accesible del enlace es el mismo texto que se ve (WCAG 2.5.3).
   */
  label: string;
  /** Ruta raíz del espacio, sin barra inicial. */
  slug: string;
  /**
   * El trabajo que resuelve el espacio, en una frase y en lenguaje de quien lo
   * usa: no cómo está hecha la pantalla («tabla con inspector», «nueve
   * cortes»). Sale junto al título del espacio, en el tooltip del rail y en la
   * paleta ⌘K.
   */
  description: string;
  /**
   * Palabras con las que la paleta ⌘K encuentra también el espacio, sin
   * pintarse en ningún sitio: los términos de oficio («CPV», «scoring»,
   * «alias») que la descripción ya no nombra.
   */
  terminos?: string;
  /** De `ICONO_ESPACIO` (`lib/iconos.ts`): uno distinto por espacio. */
  icon: LucideIcon;
  group: ConsoleGroup;
  /**
   * Quién ve el espacio. Mismo vocabulario que `SpaceView.visibility`, un nivel
   * más arriba:
   *
   * - `core` (ausente ≡ core): visible para cualquier usuario autenticado.
   * - `admin`: solo para administradores. Es un filtro de navegación, **no** un
   *   control de acceso: la autorización real la impone la API en cada endpoint.
   * - `experimental`: funciona, pero no está a la altura del resto; se marca en
   *   la UI en vez de esconderse.
   *
   * Hasta 2026-08 esto se expresaba de tres formas distintas a la vez: un
   * `Set` de slugs (`ADMIN_ONLY_SPACES`) que consultaban el rail y la paleta de
   * comandos, un `visibility` solo para vistas en `space-views.ts`, y un
   * `adminOnly` en `navigation.ts` que ya no leía nadie. Un solo campo por
   * nivel evita que las tres respuestas puedan discrepar.
   */
  visibility?: "core" | "admin" | "experimental";
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
    slug: "resumen",
    description: "Qué tienes que hacer hoy y qué ha cambiado desde tu última visita.",
    icon: ICONO_ESPACIO.resumen,
    group: "trabajo",
  },
  {
    key: "radar",
    label: "Radar",
    slug: "radar",
    description: "Licitaciones que encajan con tu perfil, para decidir cuáles seguir.",
    terminos: "puntuación score scoring señales",
    icon: ICONO_ESPACIO.radar,
    group: "trabajo",
  },
  {
    key: "detalle",
    label: "Detalle",
    slug: "detalle",
    description: "Todas las licitaciones, con filtros y exportación.",
    terminos: "listado tabla buscar expediente excel csv",
    icon: ICONO_ESPACIO.detalle,
    group: "trabajo",
  },
  {
    key: "oportunidades",
    label: "Oportunidades",
    slug: "oportunidades",
    description: "Las licitaciones que persigue tu equipo, de la decisión al contrato.",
    terminos: "pipeline tablero fases cartera rendimiento go no-go pursuits",
    icon: ICONO_ESPACIO.oportunidades,
    group: "trabajo",
    views: SPACE_VIEWS.oportunidades,
  },
  {
    key: "mercado",
    label: "Mercado",
    slug: "mercado",
    description: "Cuánto se licita, dónde y quién compra.",
    terminos: "CPV geografía tecnologías calendario renovaciones tendencias",
    icon: ICONO_ESPACIO.mercado,
    group: "analisis",
    views: SPACE_VIEWS.mercado,
  },
  {
    key: "cuentas",
    label: "Cuentas",
    slug: "cuentas",
    description: "Los órganos que tu equipo trabaja como clientes.",
    terminos: "clientes organismos seguidas",
    icon: ICONO_ESPACIO.cuentas,
    group: "trabajo",
    views: SPACE_VIEWS.cuentas,
  },
  {
    key: "direccion",
    label: "Dirección",
    slug: "direccion",
    description: "Resultados y actividad del equipo.",
    icon: ICONO_ESPACIO.direccion,
    group: "organizacion",
    // `admin` aquí es un filtro de **navegación**: la autorización real la
    // impone `GET /pursuits/direccion`, que devuelve 403 a un `member` aunque
    // teclee la URL. Un rail sin enlace es una sugerencia; el 403 es el
    // permiso.
    visibility: "admin",
    views: SPACE_VIEWS.direccion,
  },
  {
    key: "competencia",
    label: "Competencia",
    slug: "competencia",
    description: "Quién gana, cuánto y contra quién.",
    terminos: "competidores UTE adjudicatarios",
    icon: ICONO_ESPACIO.competencia,
    group: "analisis",
    views: SPACE_VIEWS.competencia,
  },
  {
    key: "investigador",
    label: "Investigador",
    slug: "investigador",
    description: "Pregunta o busca dentro de las licitaciones y sus pliegos.",
    terminos: "IA copiloto semántica preguntar",
    icon: ICONO_ESPACIO.investigador,
    group: "analisis",
  },
  {
    // Reestructura 2026-09-20: el espacio se llama «Agenda» porque responde una
    // sola pregunta y ésa es su única vista. `key` y `slug` siguen siendo
    // `mi-pipeline`: cambiarlos rompería marcadores, el redirect de
    // `/pipeline-alertas` y la serie histórica de `espacio_abierto`.
    key: "mi-pipeline",
    label: "Agenda",
    slug: "mi-pipeline",
    description: "Lo que vence pronto y lo que tienes pendiente.",
    terminos: "plazos agenda vencimientos",
    icon: ICONO_ESPACIO["mi-pipeline"],
    group: "personal",
    views: SPACE_VIEWS["mi-pipeline"],
  },
  {
    key: "mi-watchlist",
    label: "Mi Watchlist",
    slug: "mi-watchlist",
    description: "Avisos de las licitaciones que cumplen tus reglas.",
    terminos: "reglas alertas vigilancia CPV keywords",
    icon: ICONO_ESPACIO["mi-watchlist"],
    group: "personal",
  },
  {
    key: "mi-perfil",
    label: "Mi perfil",
    slug: "mi-perfil",
    description: "Qué te interesa y cuánto pesa cada criterio.",
    terminos: "scoring pesos keywords afinidad importe",
    icon: ICONO_ESPACIO["mi-perfil"],
    group: "personal",
  },
  {
    // C7.5 — un solo sitio para lo que era de uno mismo y estaba repartido.
    // Sesiones, claves y preferencias de notificación no tenían pantalla
    // ninguna (el backend de C2 las expuso y nadie las consumía); «datos y
    // cuenta» vivía en `/mi-cuenta`, que este espacio absorbe.
    key: "ajustes",
    label: "Ajustes",
    slug: "ajustes",
    description: "Tus sesiones, claves de API, avisos y datos de cuenta.",
    terminos: "API keys webhooks notificaciones cuenta",
    icon: ICONO_ESPACIO.ajustes,
    group: "personal",
    views: SPACE_VIEWS.ajustes,
  },
  {
    key: "empresas",
    label: "Empresas",
    slug: "empresas",
    description: "Fichas de empresa y alias por revisar.",
    terminos: "maestro NIF alias revisión",
    icon: ICONO_ESPACIO.empresas,
    group: "organizacion",
    views: SPACE_VIEWS.empresas,
  },
  {
    key: "equipo",
    label: "Equipo",
    slug: "equipo",
    description: "Quién está en tu organización y qué puede hacer.",
    terminos: "miembros roles permisos invitaciones",
    icon: ICONO_ESPACIO.equipo,
    group: "organizacion",
  },
  {
    key: "ops",
    label: "Ops y Admin",
    slug: "ops",
    description: "Estado del sistema, calidad de los datos y administración.",
    terminos: "observabilidad feature flags webhooks administración",
    icon: ICONO_ESPACIO.ops,
    group: "organizacion",
    visibility: "admin",
    views: SPACE_VIEWS.ops,
  },
];

/**
 * Espacios que sólo ve un administrador, derivados de `visibility`.
 *
 * Se mantiene el export porque hay tests y llamadas que lo consultan, pero ya
 * no es una lista que mantener a mano en paralelo a las definiciones: sale de
 * ellas, así que no puede quedarse desincronizada.
 */
export const ADMIN_ONLY_SPACES = new Set(
  CONSOLE_SPACES.filter((space) => space.visibility === "admin").map((space) => space.key),
);

/** ¿Puede este usuario ver el espacio? Filtro de navegación, no de acceso. */
export function isSpaceVisible(space: ConsoleSpace, isAdmin: boolean): boolean {
  return space.visibility !== "admin" || isAdmin;
}

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
 * completa (13/13): toda ruta del dashboard es superficie de consola y el
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

/** Espacio que absorbió una ruta heredada, si la absorbió alguno. */
export function spaceAbsorbing(slug: string): { space: ConsoleSpace; view: string } | undefined {
  for (const space of CONSOLE_SPACES) {
    const view = space.views?.find((candidate) => candidate.from === slug);
    if (view) return { space, view: view.key };
  }
  return undefined;
}
