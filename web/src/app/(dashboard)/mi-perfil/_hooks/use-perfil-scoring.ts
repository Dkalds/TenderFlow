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
import type * as z from "zod/mini";
import { toast } from "sonner";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { primeraVez, registrarEvento } from "@/lib/analytics";
import { perfilKeys, radarKeys } from "@/lib/query-keys";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { perfilFormulario } from "@/lib/forms/esquemas";
import { numeroDeTexto } from "@/lib/forms/valores";
import {
  DEFAULT_WEIGHTS,
  PENALIZACIONES,
  hydrateWeights,
  isValidCpv,
  partirLista,
  sumWeights,
} from "../_lib/pesos";

export type UserProfile = Schemas["UserProfileOut"];
export type CuerpoPerfil = Schemas["UserProfileBody"];

const PROFILE_KEY = perfilKeys.me;

/** Valores del formulario: las claves editables de `UserProfileBody` (S7.2). */
export type PerfilValores = z.input<typeof perfilFormulario>;

const VACIO: PerfilValores = {
  weights: { ...DEFAULT_WEIGHTS, ...PENALIZACIONES },
  afinidad_keywords: [],
  cpvs: [],
  importe_min: "",
  importe_max: "",
  visibility: "private",
};

/** Respuesta del servidor → valores del formulario. */
function valoresDe(data: UserProfile): PerfilValores {
  return {
    weights: hydrateWeights(data.weights),
    afinidad_keywords: data.afinidad_keywords ?? [],
    cpvs: data.cpvs ?? [],
    importe_min: data.importe_min != null ? String(data.importe_min) : "",
    importe_max: data.importe_max != null ? String(data.importe_max) : "",
    // Un perfil heredado es de otra persona: guardar crea uno propio, y ese
    // nace privado. Con el `organization` del heredado, quien solo quería
    // retocar sus pesos acababa compartiendo un segundo perfil con el equipo.
    visibility: data.visibility === "organization" && !data.inherited ? "organization" : "private",
  };
}

/**
 * El cuerpo que se guarda —y el que se previsualiza—: una lista vacía viaja
 * como `null` («sin preferencia») y los pesos solo si cuadran.
 */
export function cuerpoDePerfil(v: PerfilValores, organizationId: number | null | undefined): CuerpoPerfil {
  return {
    weights: sumWeights(v.weights) === 100 ? v.weights : null,
    afinidad_keywords: v.afinidad_keywords.length > 0 ? v.afinidad_keywords : null,
    cpvs: v.cpvs.length > 0 ? v.cpvs : null,
    importe_min: numeroDeTexto(v.importe_min),
    importe_max: numeroDeTexto(v.importe_max),
    organization_id: organizationId ?? null,
    visibility: v.visibility,
  };
}

export function usePerfilScoring() {
  const queryClient = useQueryClient();
  const activeOrganizationId = useActiveOrganizationId();

  // Carga del perfil actual
  const { data, isPending } = useQuery<UserProfile>({
    queryKey: [...PROFILE_KEY, activeOrganizationId],
    queryFn: () =>
      fetchWithAuth<UserProfile>(
        `/api/v1/me/profile${activeOrganizationId ? `?organization_id=${activeOrganizationId}` : ""}`,
      ),
    // El perfil de scoring es el de la organización activa: pedirlo antes de
    // saber cuál es trae el de la personal, y el formulario se rellenaría con
    // unos pesos que no son los que se están editando.
    enabled: organizacionResuelta(activeOrganizationId),
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
    form.reset(valoresDe(data));
  }, [data, form]);

  /** Cambia un campo marcándolo sucio; tras un intento de guardar, revalida. */
  function cambiar<K extends keyof PerfilValores>(campo: K, valor: PerfilValores[K]) {
    form.setValue(campo, valor as PathValue<PerfilValores, K>, {
      shouldDirty: true,
      shouldValidate: form.formState.isSubmitted,
    });
  }

  // El backend rechaza una afinidad de 100: sin palabras clave ni CPV esa
  // dimensión se omite, y no quedaría ninguna otra entre la que repartirla.
  const total = sumWeights(weights);
  const weightsValid = total === 100 && (weights.afinidad ?? 0) < 100;

  const saveMut = useMutation({
    mutationFn: (v: PerfilValores) =>
      apiMutate<UserProfile>("PUT", "/api/v1/me/profile", cuerpoDePerfil(v, activeOrganizationId)),
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
      toast.success("Perfil guardado. La puntuación ya usa tus pesos.");
    },
    onError: () => toast.error("No se pudo guardar el perfil."),
  });

  const deleteMut = useMutation({
    mutationFn: () => apiMutate("DELETE", "/api/v1/me/profile"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROFILE_KEY });
      form.reset(VACIO);
      queryClient.invalidateQueries({ queryKey: radarKeys.scoring });
      toast.success("Perfil eliminado. La puntuación vuelve a los pesos globales.");
    },
    onError: () => toast.error("No se pudo eliminar el perfil."),
  });

  function addKeyword() {
    // Pegar «sap, s/4hana; abap» son tres palabras clave, no una con comas.
    const nuevas = partirLista(kwInput)
      .map((kw) => kw.toLowerCase())
      .filter((kw, indice, todas) => !keywords.includes(kw) && todas.indexOf(kw) === indice);
    if (nuevas.length === 0) return;
    cambiar("afinidad_keywords", [...keywords, ...nuevas]);
    setKwInput("");
  }

  /** Añade un CPV; sin argumento, el que está tecleado. */
  function addCpv(codigo: string = cpvInput) {
    const cpv = codigo.trim();
    if (!isValidCpv(cpv) || cpvs.includes(cpv)) return;
    cambiar("cpvs", [...cpvs, cpv]);
    setCpvInput("");
  }

  const errores = form.formState.errors;

  const hasProfile =
    data != null &&
    (data.weights != null ||
      data.afinidad_keywords != null ||
      data.cpvs != null ||
      data.importe_min != null ||
      data.importe_max != null);

  return {
    data,
    // `isPending` y no `isLoading`: con la organización aún sin resolver la
    // consulta está retenida, y `isLoading` —que exige un fetch en vuelo— diría
    // que ya no se está cargando cuando todavía no hay nada que enseñar.
    isLoading: isPending,
    hasProfile,
    /** El perfil que se ve es el compartido de otra persona, no uno propio. */
    inherited: data?.inherited === true,
    valores,
    organizationId: activeOrganizationId,
    weights,
    weightsValid,
    setWeights: (siguientes: Record<string, number>) => cambiar("weights", siguientes),
    handleWeightChange: (name: string, value: number) => cambiar("weights", { ...weights, [name]: value }),
    handleResetWeights: () => cambiar("weights", { ...DEFAULT_WEIGHTS, ...PENALIZACIONES }),
    keywords,
    kwInput,
    setKwInput,
    addKeyword,
    removeKeyword: (kw: string) =>
      cambiar(
        "afinidad_keywords",
        keywords.filter((k) => k !== kw),
      ),
    cpvs,
    cpvInput,
    setCpvInput,
    addCpv,
    removeCpv: (cpv: string) =>
      cambiar(
        "cpvs",
        cpvs.filter((c) => c !== cpv),
      ),
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
    /** Vuelve a lo último que se cargó o se guardó, y olvida lo que se estaba tecleando. */
    descartar: () => {
      form.reset();
      setKwInput("");
      setCpvInput("");
    },
    saveMut,
    deleteMut,
  };
}
