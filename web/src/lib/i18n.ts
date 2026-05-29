/**
 * Client-side i18n — mirrors shared/i18n.py.
 *
 * Loads JSON dictionaries by locale. Cascading fallback: active locale -> "es" -> key.
 */

const DEFAULT_LOCALE = "es";
const SUPPORTED = ["es", "en"] as const;
export type Locale = (typeof SUPPORTED)[number];

// Inline translations (ported from shared/i18n_es.json / shared/i18n_en.json)
// Extend as needed — or fetch from the API in the future.
const TRANSLATIONS: Record<Locale, Record<string, string>> = {
  es: {
    "app.title": "Licitaciones SAP",
    "app.subtitle": "Plataforma de Inteligencia Competitiva",
    "nav.vista_general": "Vista General",
    "nav.mercado": "Mercado",
    "nav.competencia": "Competencia",
    "nav.personal": "Personal",
    "nav.ops": "Ops",
    "nav.admin": "Admin",
    "kpi.total_licitaciones": "Total Licitaciones",
    "kpi.importe_total": "Importe Total",
    "kpi.importe_medio": "Importe Medio",
    "kpi.organos_unicos": "Organos Unicos",
    "kpi.yoy": "YoY",
    "kpi.licitaciones_30d": "Licitaciones 30d",
    "kpi.importe_30d": "Importe 30d",
    "auth.login": "Iniciar sesion",
    "auth.logout": "Cerrar sesion",
    "auth.email": "Correo electronico",
    "auth.password": "Contrasena", // pragma: allowlist secret
    "common.loading": "Cargando...",
    "common.error": "Error",
    "common.no_data": "Sin datos",
    "common.search": "Buscar",
    "common.filter": "Filtrar",
    "common.export": "Exportar",
    "common.refresh": "Actualizar",
  },
  en: {
    "app.title": "SAP Tenders",
    "app.subtitle": "Competitive Intelligence Platform",
    "nav.vista_general": "Overview",
    "nav.mercado": "Market",
    "nav.competencia": "Competition",
    "nav.personal": "Personal",
    "nav.ops": "Ops",
    "nav.admin": "Admin",
    "kpi.total_licitaciones": "Total Tenders",
    "kpi.importe_total": "Total Amount",
    "kpi.importe_medio": "Average Amount",
    "kpi.organos_unicos": "Unique Bodies",
    "kpi.yoy": "YoY",
    "kpi.licitaciones_30d": "Tenders 30d",
    "kpi.importe_30d": "Amount 30d",
    "auth.login": "Log in",
    "auth.logout": "Log out",
    "auth.email": "Email",
    "auth.password": "Password", // pragma: allowlist secret
    "common.loading": "Loading...",
    "common.error": "Error",
    "common.no_data": "No data",
    "common.search": "Search",
    "common.filter": "Filter",
    "common.export": "Export",
    "common.refresh": "Refresh",
  },
};

let activeLocale: Locale = DEFAULT_LOCALE;

export function setLocale(locale: string): void {
  activeLocale = (SUPPORTED as readonly string[]).includes(locale)
    ? (locale as Locale)
    : DEFAULT_LOCALE;
}

export function getLocale(): Locale {
  return activeLocale;
}

export function supportedLocales(): readonly string[] {
  return SUPPORTED;
}

/**
 * Translate a key with optional interpolation.
 *
 * Cascade: active locale -> "es" -> key itself.
 */
export function t(key: string, vars?: Record<string, string | number>): string {
  const primary = TRANSLATIONS[activeLocale]?.[key];
  const fallback =
    activeLocale !== DEFAULT_LOCALE
      ? TRANSLATIONS[DEFAULT_LOCALE]?.[key]
      : undefined;
  let template = primary ?? fallback ?? key;

  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      template = template.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
    }
  }

  return template;
}
