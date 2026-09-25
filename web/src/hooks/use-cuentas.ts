"use client";

/**
 * F1.5 — cuentas objetivo: los clientes que **la organización** sigue.
 *
 * Una cuenta es un cliente con uno o varios órganos de contratación (v142): el
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
import {
  organizacionResuelta,
  useActiveOrganizationId,
  type OrganizacionActiva,
} from "@/hooks/use-organization";

export type Cuenta = Schemas["CuentaObjetivo"];
export type CuentaOrgano = Schemas["CuentaOrgano"];
export type CuentasResumen = Schemas["CuentasResumen"];
export type CuentaResumen = Schemas["CuentaResumen"];
export type FichaCuenta = Schemas["FichaCuenta"];
export type OrganoCandidato = Schemas["OrganoCandidato"];
export type AmbitoCifra = Schemas["AmbitoCifra"];

function conOrganizacion(
  url: string,
  organizationId: OrganizacionActiva,
  extra?: Record<string, string>,
): string {
  const params = new URLSearchParams(extra);
  if (organizationId != null) params.set("organization_id", String(organizationId));
  const query = params.toString();
  return query ? `${url}?${query}` : url;
}

/** El `detail` de la API cuando lo hay: «El rol viewer es de solo lectura.» dice más que un genérico. */
function motivo(error: unknown, porDefecto: string): string {
  return error instanceof Error && error.message ? error.message : porDefecto;
}

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
  });
}

/**
 * La cuenta que contiene un órgano, o `null` si la organización no lo sigue.
 *
 * Pregunta al servidor en vez de buscar en `useCuentas`: la identidad de un
 * órgano es su nombre **plegado** (`clave_de_organo`, en `db/`), y Mercado
 * pregunta con la grafía del expediente. Compararlas aquí exigiría una copia en
 * TypeScript de la tabla de plegado, que es justo lo que no puede divergir: si
 * divergiera, el botón diría «Seguir» de un órgano que ya es de una cuenta.
 */
export function useCuentaDeOrgano(organo: string | null) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: cuentaKeys.deOrgano(organizationId, organo ?? ""),
    queryFn: async (): Promise<Cuenta | null> => {
      const cuentas = await apiGet("/api/v1/cuentas", {
        params: {
          query: { organization_id: organizationId ?? undefined, organo: organo ?? undefined },
        },
      });
      return cuentas[0] ?? null;
    },
    enabled: Boolean(organo) && organizacionResuelta(organizationId),
    // Que no se sepa si el órgano es de una cuenta no merece un toast rojo
    // tapando el panel: el botón se queda sin marcar, igual que con `useFollows`.
    meta: { silent: true },
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

type ClaveDeOrgano = ReturnType<typeof cuentaKeys.deOrgano>;

interface ContextoAlta {
  clave: ClaveDeOrgano;
  previa: Cuenta | null | undefined;
}

/**
 * Sigue un órgano: el alta de un clic. Idempotente en el servidor: seguir uno
 * que ya es de una cuenta devuelve esa cuenta, con su nombre y su nota.
 *
 * Optimista sobre `deOrgano`, que es lo que pinta el botón de Mercado: el
 * control se marca en el frame del clic (es el contrato de `SeguirBoton`) y
 * vuelve si el servidor dice que no. La lista de /cuentas no se toca a mano,
 * se vuelve a pedir: el nombre con que queda la cuenta y su orden los decide el
 * servidor.
 */
export function useSeguirCuenta() {
  const qc = useQueryClient();
  const organizationId = useActiveOrganizationId();

  return useMutation<Cuenta, unknown, string, ContextoAlta>({
    mutationFn: (organo) =>
      apiMutate<Cuenta>("POST", conOrganizacion("/api/v1/cuentas", organizationId), { organo }),
    onMutate: async (organo) => {
      const clave = cuentaKeys.deOrgano(organizationId, organo);
      await qc.cancelQueries({ queryKey: clave });
      const previa = qc.getQueryData<Cuenta | null>(clave);
      const optimista: Cuenta = {
        // Id negativo, como en `use-watchlist-items`: no colisiona con ninguno
        // real y la respuesta lo sustituye.
        id: -Date.now(),
        organization_id: organizationId ?? 0,
        nombre: organo,
        organo_nombre: organo,
        organo_norm: "",
        created_at: new Date().toISOString(),
      };
      qc.setQueryData<Cuenta | null>(clave, optimista);
      return { clave, previa };
    },
    onError: (error, _organo, ctx) => {
      if (ctx) qc.setQueryData(ctx.clave, ctx.previa);
      toast.error(motivo(error, "No se pudo seguir el órgano"));
    },
    onSuccess: (cuenta, _organo, ctx) => {
      // La cuenta real sustituye a la optimista antes de la relectura.
      if (ctx) qc.setQueryData(ctx.clave, cuenta);
      // El órgano no viaja —sería un identificador, y revelaría a quién
      // persigue la organización—.
      registrarEvento("organo_seguido", { accion: "seguir" });
      // Dice a quién afecta: seguir una cuenta avisa a todo el equipo.
      toast.success(`Órgano añadido a la cuenta «${cuenta.nombre}» de tu organización`);
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: cuentaKeys.all }),
  });
}

/**
 * Quita la estrella de un órgano (Mercado): lo saca de su cuenta y, si era el
 * único, la cuenta entera. Va por nombre porque casar la grafía del expediente
 * con el órgano de la cuenta exige plegar, y eso lo hace el servidor.
 */
export function useDejarDeSeguirOrgano() {
  const qc = useQueryClient();
  const organizationId = useActiveOrganizationId();

  return useMutation<void, unknown, string, ContextoAlta>({
    mutationFn: (organo) =>
      apiMutate<void>(
        "DELETE",
        conOrganizacion("/api/v1/cuentas/por-organo", organizationId, { organo }),
      ),
    onMutate: async (organo) => {
      const clave = cuentaKeys.deOrgano(organizationId, organo);
      await qc.cancelQueries({ queryKey: clave });
      const previa = qc.getQueryData<Cuenta | null>(clave);
      qc.setQueryData<Cuenta | null>(clave, null);
      return { clave, previa };
    },
    onError: (error, _organo, ctx) => {
      if (ctx) qc.setQueryData(ctx.clave, ctx.previa);
      toast.error(motivo(error, "No se pudo dejar de seguir el órgano"));
    },
    onSuccess: () => registrarEvento("organo_seguido", { accion: "dejar_de_seguir" }),
    onSettled: () => void qc.invalidateQueries({ queryKey: cuentaKeys.all }),
  });
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
    onError: (error) => toast.error(motivo(error, "No se pudo crear la cuenta")),
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
    onError: (error) => toast.error(motivo(error, "No se pudo guardar la cuenta")),
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
    onError: (error) => toast.error(motivo(error, "No se pudieron añadir los órganos")),
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
    onError: (error) => toast.error(motivo(error, "No se pudo quitar el órgano")),
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
    onError: (error, _baja, ctx) => {
      if (ctx?.lista) qc.setQueryData(cuentaKeys.lista(organizationId), ctx.lista);
      toast.error(motivo(error, "No se pudo dejar de seguir"));
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
    onError: (error) => toast.error(motivo(error, "No se pudo recuperar la cuenta")),
    // Deshace el «dejar de seguir» que ya se midió: sin esto, la cuenta
    // recuperada contaría como una baja.
    onSuccess: () => registrarEvento("organo_seguido", { accion: "seguir" }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: cuentaKeys.all });
      void qc.invalidateQueries({ queryKey: etiquetaKeys.all });
    },
  });
}
