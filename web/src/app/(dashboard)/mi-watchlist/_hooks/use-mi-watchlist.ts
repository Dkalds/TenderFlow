/**
 * Estado, queries y mutaciones del espacio Mi Watchlist.
 *
 * La página era un único componente cliente de ~970 líneas donde las dos
 * queries, las tres mutaciones, la migración del `localStorage`, el aviso de la
 * baja de correos y todo el marcado compartían cuerpo. Con eso, retocar el
 * layout obligaba a releer la lógica de red para saber si se estaba rompiendo
 * algo, y la única forma de probar una mutación era montar la pantalla entera.
 *
 * Es el reparto que ya siguen `mercado`, `ops` y `mi-pipeline`: el
 * comportamiento en `_hooks/`, la presentación en `_components/`.
 *
 * Refactor puro: mismas rutas, mismas claves de caché, mismo orden de efectos
 * y mismas invalidaciones que tenía `page.tsx`.
 */
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { getJSON, setJSON } from "@/lib/storage";
import { primeraVez, registrarEvento } from "@/lib/analytics";
import { useMetaCcaas } from "@/hooks/use-meta-filters";
import { watchlistKeys } from "@/lib/query-keys";
import {
  activeRulesOf,
  ccaaOptions,
  dedupeMatches,
  parsePrefill,
  prefillToFormState,
  type ApiRule,
  type Frequency,
  type MatchItem,
  type RuleBody,
} from "./use-watchlist-rules";
import {
  LEGACY_KEY,
  MIGRATED_FLAG,
  useLegacyRuleMigration,
  type LegacyRule,
} from "./use-legacy-rule-migration";

/** Raíz de los endpoints de reglas (sesión por cookie, como el resto del dash). */
export const RULES_KEY = "/api/v1/watchlist/rules";

export type WatchlistTab = "reglas" | "favoritos";

/**
 * Vuelta del enlace de baja del correo.
 *
 * El backend pausa las reglas y redirige aquí con `?baja=<n>`. Sin este aviso,
 * quien pulsa el enlace aterriza en una lista de reglas que se han apagado
 * solas y no hay nada en pantalla que lo explique.
 */
function useAvisoBajaCorreos(): void {
  const searchParams = useSearchParams();
  const router = useRouter();
  const bajaAvisada = useRef(false);

  useEffect(() => {
    const baja = searchParams.get("baja");
    if (baja === null || bajaAvisada.current) return;
    bajaAvisada.current = true;
    const pausadas = Number.parseInt(baja, 10);
    toast.info(
      Number.isFinite(pausadas) && pausadas > 0
        ? `Correos pausados: ${pausadas} regla(s) en pausa. Reactívalas desde aquí cuando quieras.`
        : "No había reglas activas que pausar.",
    );
    const params = new URLSearchParams(searchParams.toString());
    params.delete("baja");
    router.replace(params.size > 0 ? `?${params.toString()}` : "/mi-watchlist", {
      scroll: false,
    });
  }, [searchParams, router]);
}

/** Campos del formulario «Nueva regla» y sus setters. */
export interface NuevaReglaForm {
  keyword: string;
  setKeyword: (value: string) => void;
  cpv: string;
  setCpv: (value: string) => void;
  minImporte: string;
  setMinImporte: (value: string) => void;
  ccaa: string;
  setCcaa: (value: string) => void;
  frequency: Frequency;
  setFrequency: (value: Frequency) => void;
  /** Crea la regla y vacía el formulario. No hace nada sin palabra clave. */
  submit: () => void;
  creating: boolean;
}

export interface MiWatchlistState {
  tab: WatchlistTab;
  setTab: (tab: WatchlistTab) => void;
  nueva: NuevaReglaForm;
  formOpen: boolean;
  setFormOpen: (open: boolean | ((previo: boolean) => boolean)) => void;
  ccaaList: string[];
  rules: ApiRule[] | undefined;
  ruleCount: number;
  rulesLoading: boolean;
  activeRules: ApiRule[];
  editingRule: ApiRule | null;
  setEditingRule: (rule: ApiRule | null) => void;
  /** Guarda la edición y cierra el panel solo si el PUT fue bien. */
  saveEdit: (id: number, body: RuleBody) => void;
  savingEdit: boolean;
  updateRule: (id: number, body: RuleBody) => void;
  deleteRule: (id: number) => void;
  combined: MatchItem[] | undefined;
  matchesLoading: boolean;
}

export function useMiWatchlist(): MiWatchlistState {
  const qc = useQueryClient();
  const searchParams = useSearchParams();
  const [tab, setTab] = useState<WatchlistTab>("reglas");

  useAvisoBajaCorreos();

  // Prefill desde la command palette: "Crear regla de watchlist con estos
  // filtros" navega aquí con ?prefill=<filterParams JSON-encoded>. Se lee
  // una sola vez como estado inicial (no en un efecto) — el usuario puede
  // seguir editando el formulario libremente después.
  const prefilled = useMemo(
    () => prefillToFormState(parsePrefill(searchParams.get("prefill"))),
    [searchParams],
  );

  const [keyword, setKeyword] = useState(() => prefilled.keyword);
  const [cpv, setCpv] = useState(() => prefilled.cpv);
  const [minImporte, setMinImporte] = useState(() => prefilled.minImporte);
  const [ccaa, setCcaa] = useState(() => prefilled.ccaa);
  const [frequency, setFrequency] = useState<Frequency>(prefilled.frequency);
  const [formOpen, setFormOpen] = useState(true);
  const [editingRule, setEditingRule] = useState<ApiRule | null>(null);

  /* ---- Reglas (server-side) ---- */
  const { data: rules, isLoading: rulesLoading } = useQuery<ApiRule[]>({
    queryKey: watchlistKeys.rules,
    queryFn: async () => {
      const data = await fetchWithAuth<{ items?: ApiRule[] }>(RULES_KEY);
      return data.items ?? [];
    },
  });

  /* ---- Migración one-shot del localStorage ---- */
  useLegacyRuleMigration({
    // fdi-allow:client-state -- lado lector de la migración one-shot a servidor
    readFlag: () => getJSON<boolean>(MIGRATED_FLAG, false),
    readLegacy: () => getJSON<LegacyRule[]>(LEGACY_KEY, []),
    markMigrated: () => setJSON(MIGRATED_FLAG, true),
    clearLegacy: () => setJSON(LEGACY_KEY, []),
    post: (body: RuleBody) => apiMutate("POST", RULES_KEY, body),
    onDone: () => qc.invalidateQueries({ queryKey: watchlistKeys.rules }),
  });

  /* ---- CCAA options (best-effort desde meta) ---- */
  const { data: metaCcaas } = useMetaCcaas();
  const ccaaList = ccaaOptions(metaCcaas);

  /* ---- Mutations ---- */
  const invalidate = () => qc.invalidateQueries({ queryKey: watchlistKeys.rules });

  const createMut = useMutation({
    mutationFn: (body: RuleBody) => apiMutate("POST", RULES_KEY, body),
    onSuccess: () => {
      invalidate();
      // Crear la primera regla de vigilancia es la señal de activación del
      // producto: es el momento en que alguien pasa de mirar el mercado a
      // pedirle al sistema que lo mire por él. `primeraVez` distingue esa
      // primera de las siguientes, que es lo que hace medible el embudo de
      // activación en vez de un contador de uso. Sin propiedades del contenido
      // de la regla: qué CPV o qué keyword vigila alguien no es una dimensión
      // de producto, es su estrategia comercial.
      registrarEvento("regla_creada", { primera_vez: primeraVez("regla") });
    },
  });
  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: RuleBody }) =>
      apiMutate("PUT", `${RULES_KEY}/${id}`, body),
    onSuccess: invalidate,
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => apiMutate("DELETE", `${RULES_KEY}/${id}`),
    onSuccess: invalidate,
  });

  const submit = () => {
    if (!keyword.trim()) return;
    createMut.mutate({
      nombre: keyword.trim(),
      keyword: keyword.trim(),
      cpv: cpv.trim() || null,
      min_importe: minImporte ? parseFloat(minImporte) : null,
      ccaa: ccaa || null,
      frequency,
      active: true,
    });
    setKeyword("");
    setCpv("");
    setMinImporte("");
    setCcaa("");
    setFrequency("daily");
  };

  const activeRules = useMemo(() => activeRulesOf(rules), [rules]);

  /* ---- Resultados combinados (matches reales por regla activa) ---- */
  const { data: combined, isLoading: matchesLoading } = useQuery<MatchItem[]>({
    queryKey: watchlistKeys.combined(activeRules.map((r) => r.id).join(",")),
    enabled: activeRules.length > 0,
    queryFn: async () => {
      const perRule = await Promise.all(
        activeRules.map(async (rule) => {
          try {
            const data = await fetchWithAuth<{ items?: MatchItem[] }>(
              `${RULES_KEY}/${rule.id}/matches?limit=20`,
            );
            return data.items ?? [];
          } catch {
            return [];
          }
        }),
      );
      return dedupeMatches(perRule);
    },
  });

  return {
    tab,
    setTab,
    nueva: {
      keyword,
      setKeyword,
      cpv,
      setCpv,
      minImporte,
      setMinImporte,
      ccaa,
      setCcaa,
      frequency,
      setFrequency,
      submit,
      creating: createMut.isPending,
    },
    formOpen,
    setFormOpen,
    ccaaList,
    rules,
    ruleCount: rules?.length ?? 0,
    rulesLoading,
    activeRules,
    editingRule,
    setEditingRule,
    saveEdit: (id, body) =>
      updateMut.mutate({ id, body }, { onSuccess: () => setEditingRule(null) }),
    savingEdit: updateMut.isPending,
    updateRule: (id, body) => updateMut.mutate({ id, body }),
    deleteRule: (id) => deleteMut.mutate(id),
    combined,
    matchesLoading,
  };
}
