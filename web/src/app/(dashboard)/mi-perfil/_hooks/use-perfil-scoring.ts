"use client";

/**
 * Perfil de scoring del usuario en el ámbito activo: carga, formulario,
 * guardado y borrado.
 *
 * El formulario es estado local sincronizado una vez por respuesta del
 * servidor; `dirty` es lo que habilita «Guardar», y los pesos solo se mandan si
 * suman 100 (el backend aplica los globales cuando llegan a `null`).
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { primeraVez, registrarEvento } from "@/lib/analytics";
import { perfilKeys, radarKeys } from "@/lib/query-keys";
import { useActiveOrganizationId } from "@/hooks/use-organization";

export interface UserProfile {
  user_key?: string | null;
  weights?: Record<string, number> | null;
  afinidad_keywords?: string[] | null;
  cpvs?: string[] | null;
  importe_min?: number | null;
  importe_max?: number | null;
  updated_at?: string | null;
  organization_id?: number | null;
  visibility?: "private" | "organization";
  inherited?: boolean;
}

// Debe reflejar `settings.SCORING_WEIGHTS`: es el reparto que el backend
// aplica a quien no tiene perfil, y el que se ofrece al crear uno.
export const DEFAULT_WEIGHTS: Record<string, number> = {
  importe: 20,
  plazo: 15,
  competencia: 20,
  margen: 20,
  afinidad: 15,
  senal_tecnica: 10,
};

const PROFILE_KEY = perfilKeys.me;

function sumWeights(w: Record<string, number>): number {
  return Object.values(w).reduce((a, b) => a + b, 0);
}

/**
 * Pesos guardados → formulario, completando las dimensiones que falten con 0.
 *
 * Un perfil creado antes de que existiera una dimensión no la trae. Sin este
 * relleno, su slider no aparecería y el usuario no podría activarla nunca; con
 * el 0 explícito la ve, sabe que no está puntuando, y la suma sigue en 100.
 */
function hydrateWeights(saved: Record<string, number> | null | undefined): Record<string, number> {
  if (!saved) return DEFAULT_WEIGHTS;
  const ceros = Object.fromEntries(Object.keys(DEFAULT_WEIGHTS).map((k) => [k, 0]));
  return { ...ceros, ...saved };
}

/** Mismo criterio que valida el backend: división, grupo o código completo. */
export function isValidCpv(value: string): boolean {
  return /^\d{4,8}$/.test(value.trim());
}

export function usePerfilScoring() {
  const queryClient = useQueryClient();
  const activeOrganizationId = useActiveOrganizationId();

  // Carga del perfil actual
  const { data, isLoading } = useQuery<UserProfile>({
    queryKey: [...PROFILE_KEY, activeOrganizationId],
    queryFn: () =>
      fetchWithAuth<UserProfile>(
        `/api/v1/me/profile${activeOrganizationId ? `?organization_id=${activeOrganizationId}` : ""}`,
      ),
    staleTime: 60_000,
  });

  // Estado local del formulario
  const [weights, setWeights] = useState<Record<string, number>>(DEFAULT_WEIGHTS);
  const [keywords, setKeywords] = useState<string[]>([]);
  const [kwInput, setKwInput] = useState("");
  const [cpvs, setCpvs] = useState<string[]>([]);
  const [cpvInput, setCpvInput] = useState("");
  const [importeMin, setImporteMin] = useState("");
  const [importeMax, setImporteMax] = useState("");
  const [sharedWithOrganization, setSharedWithOrganization] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Rellenar formulario cuando llegan datos del servidor
  useEffect(() => {
    if (!data) return;
    setWeights(hydrateWeights(data.weights)); // eslint-disable-line react-hooks/set-state-in-effect
    setKeywords(data.afinidad_keywords ?? []);
    setCpvs(data.cpvs ?? []);
    setImporteMin(data.importe_min != null ? String(data.importe_min) : "");
    setImporteMax(data.importe_max != null ? String(data.importe_max) : "");
    setSharedWithOrganization(data.visibility === "organization");
    setDirty(false);
  }, [data]);

  // Validación de suma de pesos
  const total = sumWeights(weights);
  const weightsValid = total === 100;

  const saveMut = useMutation({
    mutationFn: () =>
      apiMutate<UserProfile>("PUT", "/api/v1/me/profile", {
        weights: weightsValid ? weights : null,
        afinidad_keywords: keywords.length > 0 ? keywords : null,
        cpvs: cpvs.length > 0 ? cpvs : null,
        importe_min: importeMin !== "" ? Number(importeMin) : null,
        importe_max: importeMax !== "" ? Number(importeMax) : null,
        organization_id: activeOrganizationId,
        visibility: sharedWithOrganization ? "organization" : "private",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROFILE_KEY });
      queryClient.invalidateQueries({ queryKey: radarKeys.scoring });
      setDirty(false);
      // Primer paso del embudo de activación («Primeros pasos» en /resumen) y
      // el que más pesa: hasta que existe este perfil, el Radar puntúa con los
      // pesos genéricos de `settings.SCORING_WEIGHTS` y el orden que ve el
      // usuario es el de otro. `primeraVez` separa esa configuración inicial de
      // los reajustes, que son uso normal. Sin propiedades del contenido: los
      // pesos, las keywords y los CPV son la estrategia comercial de quien los
      // pone, no una dimensión de producto.
      registrarEvento("perfil_configurado", { primera_vez: primeraVez("perfil") });
      toast.success("Perfil guardado. El scoring usará tus pesos personalizados.");
    },
    onError: () => toast.error("No se pudo guardar el perfil."),
  });

  const deleteMut = useMutation({
    mutationFn: () => apiMutate("DELETE", "/api/v1/me/profile"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROFILE_KEY });
      setWeights(DEFAULT_WEIGHTS);
      setKeywords([]);
      setCpvs([]);
      setImporteMin("");
      setImporteMax("");
      setSharedWithOrganization(false);
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: radarKeys.scoring });
      toast.success("Perfil eliminado. El scoring vuelve a los valores globales.");
    },
    onError: () => toast.error("No se pudo eliminar el perfil."),
  });

  function handleWeightChange(name: string, value: number) {
    setWeights((prev) => ({ ...prev, [name]: value }));
    setDirty(true);
  }

  function handleResetWeights() {
    setWeights(DEFAULT_WEIGHTS);
    setDirty(true);
  }

  function addKeyword() {
    const kw = kwInput.trim().toLowerCase();
    if (!kw || keywords.includes(kw)) return;
    setKeywords((prev) => [...prev, kw]);
    setKwInput("");
    setDirty(true);
  }

  function removeKeyword(kw: string) {
    setKeywords((prev) => prev.filter((k) => k !== kw));
    setDirty(true);
  }

  function addCpv() {
    const cpv = cpvInput.trim();
    if (!isValidCpv(cpv) || cpvs.includes(cpv)) return;
    setCpvs((prev) => [...prev, cpv]);
    setCpvInput("");
    setDirty(true);
  }

  function removeCpv(cpv: string) {
    setCpvs((prev) => prev.filter((c) => c !== cpv));
    setDirty(true);
  }

  function setImporteMinValue(value: string) {
    setImporteMin(value);
    setDirty(true);
  }

  function setImporteMaxValue(value: string) {
    setImporteMax(value);
    setDirty(true);
  }

  function setSharedValue(checked: boolean) {
    setSharedWithOrganization(checked);
    setDirty(true);
  }

  const hasProfile =
    data &&
    (data.weights != null ||
      data.afinidad_keywords != null ||
      data.cpvs != null ||
      data.importe_min != null ||
      data.importe_max != null);

  return {
    data,
    isLoading,
    hasProfile,
    weights,
    total,
    weightsValid,
    handleWeightChange,
    handleResetWeights,
    keywords,
    kwInput,
    setKwInput,
    addKeyword,
    removeKeyword,
    cpvs,
    cpvInput,
    setCpvInput,
    addCpv,
    removeCpv,
    importeMin,
    setImporteMin: setImporteMinValue,
    importeMax,
    setImporteMax: setImporteMaxValue,
    sharedWithOrganization,
    setSharedWithOrganization: setSharedValue,
    dirty,
    saveMut,
    deleteMut,
  };
}
