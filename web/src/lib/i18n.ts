/**
 * Client-side i18n — loads translations from /public/locales/{locale}.json.
 *
 * Uses a Zustand micro-store for reactive locale state.
 * Cascading fallback: active locale -> "es" -> key itself.
 *
 * Translations are fetched only once and cached in memory.
 * The inline objects serve as fallback if the fetch fails.
 */
import { create } from "zustand";
import { reportError } from "@/lib/report-error";
import esInline from "../../public/locales/es.json";
import enInline from "../../public/locales/en.json";

const DEFAULT_LOCALE = "es";
const SUPPORTED = ["es", "en"] as const;
export type Locale = (typeof SUPPORTED)[number];

/** Cache for dynamically loaded translations */
const _remoteCache = new Map<Locale, Record<string, string>>();

async function loadLocale(locale: Locale): Promise<Record<string, string>> {
  if (_remoteCache.has(locale)) return _remoteCache.get(locale)!;
  // Skip fetch during SSR — relative URL won't resolve
  if (typeof window === "undefined") {
    return { ...(_inline[locale] ?? _inline.es) };
  }
  try {
    const res = await fetch(`/locales/${locale}.json`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data: Record<string, string> = await res.json();
    _remoteCache.set(locale, data);
    return data;
  } catch (err) {
    if (process.env.NODE_ENV === "development") {
      console.warn(`[i18n] Falling back to inline translations for "${locale}"`, err);
    }
    return { ...(_inline[locale] ?? _inline.es) };
  }
}

/** Inline fallback translations keyed by locale */
const _inline: Record<Locale, Record<string, string>> = {
  es: esInline as Record<string, string>,
  en: enInline as Record<string, string>,
};

/** Merged translations (remote loaded + inline fallback) */
function getTranslations(locale: Locale): Record<string, string> {
  return { ...(_inline[locale] ?? {}), ...(_remoteCache.get(locale) ?? {}) };
}

// ---------------------------------------------------------------------------
// Zustand store — reactive locale state
// ---------------------------------------------------------------------------

interface LocaleState {
  locale: Locale;
  loaded: boolean;
  setLocale: (locale: string) => void;
}

export const useLocale = create<LocaleState>((set) => ({
  locale: DEFAULT_LOCALE,
  loaded: true,
  setLocale: (locale: string) =>
    set({
      locale: (SUPPORTED as readonly string[]).includes(locale)
        ? (locale as Locale)
        : DEFAULT_LOCALE,
    }),
}));

// Preload translations on first import (browser only, quiet fallback)
loadLocale("es").catch(() => {});
loadLocale("en").catch(() => {});

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
 * For non-reactive contexts, reads from the Zustand store directly.
 * For reactive usage, call `useLocale()` first then pass locale to `tWithLocale()`.
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
  const translations = getTranslations(locale);
  const primary = translations[key];
  const fallback =
    locale !== DEFAULT_LOCALE ? getTranslations(DEFAULT_LOCALE)[key] : undefined;
  let template = primary ?? fallback ?? key;

  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      template = template.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
    }
  }

  return template;
}

/**
 * Preload translations for a locale (call on app init or locale switch).
 * Translations are cached after first load.
 */
export async function preloadLocale(locale: Locale): Promise<void> {
  await loadLocale(locale);
}
