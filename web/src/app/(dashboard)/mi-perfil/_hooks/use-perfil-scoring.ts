"use client";

/**
 * Perfil de scoring del usuario en el ámbito activo: carga, formulario,
 * guardado y borrado.
 *
 * El formulario es react-hook-form con el esquema de `UserProfileBody` (S7.2),
 * reiniciado una vez por respuesta del servidor; `dirty` es lo que habilita
 * «Guardar», y los pesos solo se mandan si suman 100 (el backend aplica los
 * globales cuando llegan a `null`).
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm, useWatch, type PathValue } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import type { z } from "zod";
import { toast } from "sonner";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { primeraVez, registrarEvento } from "@/lib/analytics";
import { perfilKeys, radarKeys } from "@/lib/query-keys";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import { perfilFormulario } from "@/lib/forms/esquemas";
import { numeroDeTexto } from "@/lib/forms/valores";

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

/** Valores del formulario: las claves editables de `UserProfileBody` (S7.2). */
export type PerfilValores = z.input<typeof perfilFormulario>;

const VACIO: PerfilValores = {
  weights: DEFAULT_WEIGHTS,
  afinidad_keywords: [],
  cpvs: [],
  importe_min: "",
  importe_max: "",
  visibility: "private",
};

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

  // Valores del formulario: claves de `UserProfileBody` con el esquema de
  // S7.2. Lo que se está tecleando en los dos campos de «añadir» no es del
  // contrato hasta que se añade, así que sigue fuera, en estado local.
  const form = useForm<PerfilValores>({ resolver: zodResolver(perfilFormulario), defaultValues: VACIO });
  const valores = useWatch({ control: form.control }) as PerfilValores;
  const { weights, afinidad_keywords: keywords, cpvs } = valores;
  const [kwInput, setKwInput] = useState("");
  const [cpvInput, setCpvInput] = useState("");

  // Rellenar formulario cuando llegan datos del servidor; `reset` deja además
  // esos valores como referencia de «sin cambios» (`isDirty`).
  useEffect(() => {
    if (!data) return;
    form.reset({
      weights: hydrateWeights(data.weights),
      afinidad_keywords: data.afinidad_keywords ?? [],
      cpvs: data.cpvs ?? [],
      importe_min: data.importe_min != null ? String(data.importe_min) : "",
      importe_max: data.importe_max != null ? String(data.importe_max) : "",
      visibility: data.visibility === "organization" ? "organization" : "private",
    });
  }, [data, form]);

  /** Cambia un campo marcándolo sucio; tras un intento de guardar, revalida. */
  function cambiar<K extends keyof PerfilValores>(campo: K, valor: PerfilValores[K]) {
    form.setValue(campo, valor as PathValue<PerfilValores, K>, {
      shouldDirty: true,
      shouldValidate: form.formState.isSubmitted,
    });
  }

  // Validación de suma de pesos
  const total = sumWeights(weights);
  const weightsValid = total === 100;

  const saveMut = useMutation({
    mutationFn: (v: PerfilValores) =>
      apiMutate<UserProfile>("PUT", "/api/v1/me/profile", {
        weights: sumWeights(v.weights) === 100 ? v.weights : null,
        afinidad_keywords: v.afinidad_keywords.length > 0 ? v.afinidad_keywords : null,
        cpvs: v.cpvs.length > 0 ? v.cpvs : null,
        importe_min: numeroDeTexto(v.importe_min),
        importe_max: numeroDeTexto(v.importe_max),
        organization_id: activeOrganizationId,
        visibility: v.visibility,
      }),
    onSuccess: (_respuesta, v) => {
      queryClient.invalidateQueries({ queryKey: PROFILE_KEY });
      queryClient.invalidateQueries({ queryKey: radarKeys.scoring });
      form.reset(v);
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
      form.reset(VACIO);
      queryClient.invalidateQueries({ queryKey: radarKeys.scoring });
      toast.success("Perfil eliminado. El scoring vuelve a los valores globales.");
    },
    onError: () => toast.error("No se pudo eliminar el perfil."),
  });

  function handleWeightChange(name: string, value: number) {
    cambiar("weights", { ...weights, [name]: value });
  }

  function handleResetWeights() {
    cambiar("weights", DEFAULT_WEIGHTS);
  }

  function addKeyword() {
    const kw = kwInput.trim().toLowerCase();
    if (!kw || keywords.includes(kw)) return;
    cambiar("afinidad_keywords", [...keywords, kw]);
    setKwInput("");
  }

  function removeKeyword(kw: string) {
    cambiar(
      "afinidad_keywords",
      keywords.filter((k) => k !== kw),
    );
  }

  function addCpv() {
    const cpv = cpvInput.trim();
    if (!isValidCpv(cpv) || cpvs.includes(cpv)) return;
    cambiar("cpvs", [...cpvs, cpv]);
    setCpvInput("");
  }

  function removeCpv(cpv: string) {
    cambiar(
      "cpvs",
      cpvs.filter((c) => c !== cpv),
    );
  }

  const errores = form.formState.errors;

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
    importeMin: valores.importe_min,
    setImporteMin: (value: string) => cambiar("importe_min", value),
    importeMax: valores.importe_max,
    setImporteMax: (value: string) => cambiar("importe_max", value),
    /** Errores de campo del esquema, ya como texto. */
    errores: {
      importe_min: errores.importe_min?.message,
      importe_max: errores.importe_max?.message,
      cpvs: errores.cpvs?.message ?? errores.cpvs?.root?.message,
    },
    sharedWithOrganization: valores.visibility === "organization",
    setSharedWithOrganization: (checked: boolean) => cambiar("visibility", checked ? "organization" : "private"),
    dirty: form.formState.isDirty,
    /** Valida con el esquema y guarda; con errores, los enseña y no pide nada. */
    guardar: () => void form.handleSubmit((v) => saveMut.mutate(v))(),
    saveMut,
    deleteMut,
  };
}
