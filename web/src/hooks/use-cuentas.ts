"use client";

/**
 * F1.5 — cuentas objetivo: los clientes que **la organización** sigue.
 *
 * Una cuenta es un cliente con uno o varios órganos de contratación (v145): el
 * Ayuntamiento de Madrid contrata a través de seis órganos y ninguno se llama
 * así. Es el único «seguir un órgano» con efectos: avisa a todos los miembros
 * activos de las publicaciones nuevas de sus órganos y de sus contratos que
 * entran en los seis meses previos a su fin (`services/avisos_outbox.py`), y
 * entra en el cruce de las alertas de competidores («ha ganado en X, que
 * sigues»). `follows` también admite `target_type='organo'` (ADR-031 §A), pero
 * es personal y nada lo lee: el botón «Seguir» del panel de órgano de Mercado
 * escribía ahí y no avisaba a nadie. Desde 2026-09-25 las dos puertas —ese
 * botón, vía `useSeguimiento`, y /cuentas— pasan por estos hooks. Por eso viven
 * aquí y no en la página: dos mutaciones serían dos formas de medir y de
 * invalidar la misma cosa.
 *
 * **Ámbito: la organización activa**, como las etiquetas. Sin
 * `organization_id` el backend resuelve la personal, y una cuenta creada ahí
 * sólo le avisa a quien la creó, que es lo contrario de una decisión de
 * equipo. Es lo que hacía /cuentas hasta 2026-09-25, mientras guardaba las
 * etiquetas de esas mismas cuentas en la organización activa.
 *
 * Un `viewer` puede leer pero no escribir: la API responde 403 y el aviso de
 * error enseña su motivo. Las pantallas además esconden lo que no puede hacer
 * (`usePuedeEscribir`).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiGet, apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { registrarEvento } from "@/lib/analytics";
import { cuentaKeys, etiquetaKeys } from "@/lib/query-keys";
import { useDebounce } from "@/hooks/use-debounce";
import { MIN_LONGITUD_BUSQUEDA } from "@/hooks/use-busqueda-global";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { conOrganizacion } from "@/hooks/use-seguir-cuenta";

// Seguir y dejar de seguir un órgano viven en `use-seguir-cuenta.ts` (ver allí
// por qué); se reexportan para quien gestiona cuentas desde aquí.
export { useCuentaDeOrgano, useDejarDeSeguirOrgano, useSeguirCuenta } from "@/hooks/use-seguir-cuenta";

export type Cuenta = Schemas["CuentaObjetivo"];
export type CuentaOrgano = Schemas["CuentaOrgano"];
export type CuentasResumen = Schemas["CuentasResumen"];
export type CuentaResumen = Schemas["CuentaResumen"];
export type FichaCuenta = Schemas["FichaCuenta"];
export type OrganoCandidato = Schemas["OrganoCandidato"];
export type AmbitoCifra = Schemas["AmbitoCifra"];

/** La cartera de cuentas de la organización activa, ordenada por nombre. */
export function useCuentas() {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: cuentaKeys.lista(organizationId),
    queryFn: () =>
      apiGet("/api/v1/cuentas", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    enabled: organizacionResuelta(organizationId),
    meta: META_ERROR_EN_LINEA,
  });
}

/**
 * Los cuatro números de cada cuenta, con el universo y la ventana de cada uno
 * (ADR-014). Va aparte de la lista: es más caro de calcular, y la lista no
 * tiene que esperarlo para pintarse.
 */
export function useCuentasResumen() {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: cuentaKeys.resumen(organizationId),
    queryFn: () =>
      apiGet("/api/v1/cuentas/resumen", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    enabled: organizacionResuelta(organizationId),
    staleTime: 60_000,
  });
}

/** La ficha de una cuenta: sus órganos, publicaciones, vencimientos y oportunidades. */
export function useFichaCuenta(cuentaId: number | null) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: cuentaKeys.ficha(organizationId, cuentaId ?? 0),
    queryFn: () =>
      fetchWithAuth<FichaCuenta>(conOrganizacion(`/api/v1/cuentas/${cuentaId}`, organizationId)),
    enabled: cuentaId != null && cuentaId > 0 && organizacionResuelta(organizationId),
    staleTime: 60_000,
    meta: META_ERROR_EN_LINEA,
  });
}

/**
 * Órganos reales para el alta de una cuenta, con sus expedientes y la cuenta
 * que ya tiene cada uno. Es lo que evita la cuenta que no casa con nada: se
 * elige un órgano que existe en vez de escribir un nombre a ciegas.
 *
 * Mismo mínimo y mismo debounce que la paleta de búsqueda, y por lo mismo: el
 * campo pregunta en cada tecla, y con menos de tres caracteres cualquier
 * término casa con media tabla.
 */
export function useBuscarOrganos(termino: string) {
  const organizationId = useActiveOrganizationId();
  const q = useDebounce(termino.trim(), 250);
  const activa = q.length >= MIN_LONGITUD_BUSQUEDA;
  const query = useQuery({
    queryKey: cuentaKeys.buscarOrganos(organizationId, q),
    queryFn: ({ signal }) =>
      apiGet("/api/v1/cuentas/buscar-organos", {
        params: { query: { q, organization_id: organizationId ?? undefined } },
        signal,
      }),
    enabled: activa && organizacionResuelta(organizationId),
    // Mientras llega la respuesta del término nuevo se ven los candidatos del
    // anterior, que casi siempre siguen valiendo: vaciar la lista en cada
    // tecla la haría parpadear.
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: false,
    meta: { silent: true },
  });
  return {
    q,
    activa,
    /** El término tecleado aún no ha llegado al debounce. */
    pendiente: termino.trim() !== q,
    candidatos: activa ? (query.data ?? []) : [],
    isFetching: activa && query.isFetching,
    isError: activa && query.isError,
  };
}

export interface AltaDeCuenta {
  nombre?: string;
  organos: string[];
  nota?: string;
}

/**
 * Crea una cuenta con uno o varios órganos, todo o nada. El 409 del servidor
 * nombra el conflicto («ya está en la cuenta X», «ya hay una cuenta llamada
 * Y») y es lo que enseña el aviso.
 */
export function useCrearCuenta() {
  const qc = useQueryClient();
  const organizationId = useActiveOrganizationId();

  return useMutation<Cuenta, unknown, AltaDeCuenta>({
    mutationFn: ({ nombre, organos, nota }) =>
      apiMutate<Cuenta>("POST", conOrganizacion("/api/v1/cuentas", organizationId), {
        organos,
        ...(nombre?.trim() ? { nombre: nombre.trim() } : {}),
        ...(nota?.trim() ? { nota: nota.trim() } : {}),
      }),
    meta: { errorTitle: "No se pudo crear la cuenta" },
    onSuccess: (cuenta) => {
      registrarEvento("organo_seguido", { accion: "seguir" });
      toast.success(`Cuenta «${cuenta.nombre}» creada: avisará a todo el equipo`);
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: cuentaKeys.all }),
  });
}

export interface EdicionDeCuenta {
  cuentaId: number;
  nombre?: string;
  /** `null` borra la nota; ausente, no se toca. */
  nota?: string | null;
}

/** Renombra la cuenta o cambia su nota. */
export function useEditarCuenta() {
  const qc = useQueryClient();
  const organizationId = useActiveOrganizationId();

  return useMutation<Cuenta, unknown, EdicionDeCuenta>({
    mutationFn: ({ cuentaId, ...cambios }) =>
      apiMutate<Cuenta>(
        "PATCH",
        conOrganizacion(`/api/v1/cuentas/${cuentaId}`, organizationId),
        cambios,
      ),
    meta: { errorTitle: "No se pudo guardar la cuenta" },
    onSettled: () => void qc.invalidateQueries({ queryKey: cuentaKeys.all }),
  });
}

/** Añade órganos a una cuenta, todo o nada. */
export function useAnadirOrganos() {
  const qc = useQueryClient();
  const organizationId = useActiveOrganizationId();

  return useMutation<Cuenta, unknown, { cuentaId: number; organos: string[] }>({
    mutationFn: ({ cuentaId, organos }) =>
      apiMutate<Cuenta>(
        "POST",
        conOrganizacion(`/api/v1/cuentas/${cuentaId}/organos`, organizationId),
        { organos },
      ),
    meta: { errorTitle: "No se pudieron añadir los órganos" },
    onSettled: () => void qc.invalidateQueries({ queryKey: cuentaKeys.all }),
  });
}

/** Quita un órgano de una cuenta. El último no se puede quitar (409). */
export function useQuitarOrgano() {
  const qc = useQueryClient();
  const organizationId = useActiveOrganizationId();

  return useMutation<Cuenta, unknown, { cuentaId: number; cuentaOrganoId: number }>({
    mutationFn: ({ cuentaId, cuentaOrganoId }) =>
      apiMutate<Cuenta>(
        "DELETE",
        conOrganizacion(`/api/v1/cuentas/${cuentaId}/organos/${cuentaOrganoId}`, organizationId),
      ),
    meta: { errorTitle: "No se pudo quitar el órgano" },
    onSettled: () => void qc.invalidateQueries({ queryKey: cuentaKeys.all }),
  });
}

interface ContextoBaja {
  lista: Cuenta[] | undefined;
}

/**
 * Deja de seguir una cuenta, por su id: se lleva sus órganos y sus etiquetas.
 * Cualquier miembro puede, no sólo quien la creó: la cartera es del equipo.
 */
export function useDejarDeSeguirCuenta() {
  const qc = useQueryClient();
  const organizationId = useActiveOrganizationId();

  return useMutation<void, unknown, { id: number }, ContextoBaja>({
    mutationFn: ({ id }) =>
      apiMutate<void>("DELETE", conOrganizacion(`/api/v1/cuentas/${id}`, organizationId)),
    onMutate: async ({ id }) => {
      await qc.cancelQueries({ queryKey: cuentaKeys.all });
      const claveLista = cuentaKeys.lista(organizationId);
      const lista = qc.getQueryData<Cuenta[]>(claveLista);
      qc.setQueryData<Cuenta[]>(claveLista, (vieja) => vieja?.filter((c) => c.id !== id));
      return { lista };
    },
    meta: { errorTitle: "No se pudo dejar de seguir" },
    onError: (_error, _baja, ctx) => {
      if (ctx?.lista) qc.setQueryData(cuentaKeys.lista(organizationId), ctx.lista);
    },
    onSuccess: () => registrarEvento("organo_seguido", { accion: "dejar_de_seguir" }),
    onSettled: () => void qc.invalidateQueries({ queryKey: cuentaKeys.all }),
  });
}

/** Lo que hace falta para rehacer una cuenta tras «Deshacer». */
export interface CopiaDeCuenta {
  nombre: string;
  organos: string[];
  nota: string | null;
  etiquetaIds: number[];
}

/**
 * «Deshacer» de dejar de seguir: vuelve a crear la cuenta con su nombre, sus
 * órganos y su nota, y le vuelve a poner sus etiquetas.
 *
 * Rehace en vez de retrasar el borrado. Un borrado diferido —esperar a que el
 * aviso se cierre para mandar el DELETE— se pierde si la pestaña se cierra
 * antes, y la lista del equipo diría una cosa y la base otra. La cuenta
 * rehecha tiene otro id; lo que el equipo ve —nombre, órganos, nota,
 * etiquetas— es el mismo.
 */
export function useRecuperarCuenta() {
  const qc = useQueryClient();
  const organizationId = useActiveOrganizationId();

  return useMutation<Cuenta, unknown, CopiaDeCuenta>({
    mutationFn: async ({ nombre, organos, nota, etiquetaIds }) => {
      const cuenta = await apiMutate<Cuenta>(
        "POST",
        conOrganizacion("/api/v1/cuentas", organizationId),
        { nombre, organos, ...(nota ? { nota } : {}) },
      );
      for (const etiquetaId of etiquetaIds) {
        await apiMutate(
          "POST",
          conOrganizacion("/api/v1/etiquetas/aplicar", organizationId),
          { etiqueta_id: etiquetaId, objeto_tipo: "cuenta", objeto_id: String(cuenta.id) },
        );
      }
      return cuenta;
    },
    meta: { errorTitle: "No se pudo recuperar la cuenta" },
    // Deshace el «dejar de seguir» que ya se midió: sin esto, la cuenta
    // recuperada contaría como una baja.
    onSuccess: () => registrarEvento("organo_seguido", { accion: "seguir" }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: cuentaKeys.all });
      void qc.invalidateQueries({ queryKey: etiquetaKeys.all });
    },
  });
}
