/**
 * Client-side i18n — mirrors shared/i18n.py.
 *
 * Uses a Zustand micro-store so locale changes trigger React re-renders.
 * Cascading fallback: active locale -> "es" -> key itself.
 */
import { create } from "zustand";

const DEFAULT_LOCALE = "es";
const SUPPORTED = ["es", "en"] as const;
export type Locale = (typeof SUPPORTED)[number];

// Inline translations (ported from shared/i18n_es.json / shared/i18n_en.json)
// Extend as needed — or fetch from the API in the future.
const TRANSLATIONS: Record<Locale, Record<string, string>> = {
  es: {
    "app.title": "TenderFlow",
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
    "common.retry": "Reintentar",
    "common.no_data_hint": "Ajusta los filtros o el rango de fechas para ver resultados.",
    "common.empty_filtered": "Sin resultados para los filtros actuales.",
    "common.chart_error": "No se pudo cargar el grafico.",
  },
  en: {
    "app.title": "TenderFlow",
    "app.subtitle": "Market Intelligence",
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
    "common.retry": "Retry",
    "common.no_data_hint": "Try adjusting the filters or the date range.",
    "common.empty_filtered": "No results for the current filters.",
    "common.chart_error": "Couldn't load the chart.",
  },
};

// ---------------------------------------------------------------------------
// Zustand store — reactive locale state
// ---------------------------------------------------------------------------

interface LocaleState {
  locale: Locale;
  setLocale: (locale: string) => void;
}

export const useLocale = create<LocaleState>((set) => ({
  locale: DEFAULT_LOCALE,
  setLocale: (locale: string) =>
    set({
      locale: (SUPPORTED as readonly string[]).includes(locale)
        ? (locale as Locale)
        : DEFAULT_LOCALE,
    }),
}));

// ---------------------------------------------------------------------------
// Public helpers
// ---------------------------------------------------------------------------

/** @deprecated Use `useLocale()` hook for reactive access. */
export function setLocale(locale: string): void {
  useLocale.getState().setLocale(locale);
}

/** @deprecated Use `useLocale()` hook for reactive access. */
export function getLocale(): Locale {
  return useLocale.getState().locale;
}

export function supportedLocales(): readonly string[] {
  return SUPPORTED;
}

/**
 * Translate a key with optional interpolation.
 *
 * Cascade: active locale -> "es" -> key itself.
 *
 * For non-reactive contexts (event handlers, utils), reads from
 * the Zustand store directly. For reactive usage within components,
 * call `useLocale()` first so the component re-renders on locale change,
 * then pass the locale to `tWithLocale()`.
 */
export function t(key: string, vars?: Record<string, string | number>): string {
  const activeLocale = useLocale.getState().locale;
  return tWithLocale(activeLocale, key, vars);
}

/**
 * Pure translate function — accepts locale explicitly.
 * Useful inside components that subscribe to useLocale().
 */
export function tWithLocale(
  locale: Locale,
  key: string,
  vars?: Record<string, string | number>,
): string {
  const primary = TRANSLATIONS[locale]?.[key];
  const fallback =
    locale !== DEFAULT_LOCALE
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
