"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet, fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { pursuitKeys } from "@/hooks/use-pursuits";
import {
  organizacionResuelta,
  useActiveOrganizationId,
  useOrganizations,
  useRolActivo,
} from "@/hooks/use-organization";
import { faltaCapacidad, hayNif, hayRegla, tienePursuits } from "@/components/onboarding/senales";
import type { PasoId, SenalPaso } from "@/components/onboarding/pasos";
import { organizationKeys, watchlistKeys } from "@/lib/query-keys";

/**
 * De qué dato del servidor sale cada primer paso.
 *
 * No hay endpoint de onboarding y no lo va a haber: un campo
 * `onboarding_completado` pediría una migración (prohibida) para guardar algo
 * que ya es deducible. Los pasos se leen de superficies que la API ya sirve:
 *
 * | paso      | endpoint                               | «hecho» cuando                                      |
 * | --------- | -------------------------------------- | --------------------------------------------------- |
 * | capacidad | `GET /organizations/{id}/capabilities` | `campos_incompletos` no trae certificaciones ni facturación… |
 * |           | `GET /organizations/{id}/nifs`         | …y hay al menos un NIF                              |
 * | alerta    | `GET /watchlist/rules`                 | hay al menos una regla                              |
 * | pursuit   | `GET /pursuits`                        | `total > 0`                                         |
 *
 * Las claves de caché son deliberadamente las mismas que usan `/equipo`,
 * `mi-watchlist` y `usePursuits`: quien venga de esas pantallas no paga una
 * segunda petición, y guardar allí actualiza esto de rebote.
 *
 * **Los NIFs solo los sirve la API a owner y admin** (lo que revelan es con
 * qué identidad concurre la casa). A los demás roles no se les piden —sería un
 * 403 seguro—, así que su paso de capacidad solo puede afirmarse pendiente
 * (falta certificación o facturación, que sí pueden leer) o quedarse «sin
 * comprobar». Nunca «hecho»: no se sabe si hay NIF (ADR-014).
 *
 * `activo` apaga todas las queries de golpe. Un veterano que ya ocultó la
 * banda no debe pagar peticiones en la pantalla de entrada para no ver nada.
 */

/** Cinco minutos: nada de esto cambia mientras se mira el Resumen. */
const STALE = 5 * 60_000;

/** Quien puede leer (y declarar) los NIFs de la organización. */
const ROLES_GESTORES: ReadonlySet<string> = new Set(["owner", "admin"]);

/** Envuelve una query en la señal de tres estados que consume `derivarPasos`. */
function senalDe<T>(
  query: { data: T | undefined; isError: boolean },
  cumple: (data: T) => boolean,
): SenalPaso {
  if (query.isError) return "error";
  if (query.data === undefined) return "cargando";
  return cumple(query.data);
}

/**
 * Capacidad + NIF en una señal. Lo que falta del perfil ya basta para decir
 * «pendiente» sin esperar al NIF; para decir «hecho» hacen falta los dos.
 */
export function senalCapacidad(perfil: SenalPaso, nif: SenalPaso): SenalPaso {
  if (perfil === false) return false;
  if (perfil !== true) return perfil;
  return nif;
}

export function useSenalesOnboarding(activo: boolean): Partial<Record<PasoId, SenalPaso>> {
  // `useActiveOrganizationId` ya resuelve `["organizations"]`; pedirlo otra vez
  // es gratis (misma clave) y aquí hace falta además saber si esa query falló,
  // que el id resuelto por sí solo no lo cuenta.
  const organizations = useOrganizations();
  const organizationId = useActiveOrganizationId();
  const rol = useRolActivo();
  const conOrganizacion = typeof organizationId === "number";
  const gestiona = rol !== undefined && ROLES_GESTORES.has(rol);

  const capacidad = useQuery({
    queryKey: organizationKeys.capabilities(organizationId),
    queryFn: () =>
      fetchWithAuth<Schemas["OrganizationCapabilitiesOut"]>(
        `/api/v1/organizations/${organizationId}/capabilities`,
      ),
    enabled: activo && conOrganizacion,
    staleTime: STALE,
  });

  const nifs = useQuery({
    queryKey: organizationKeys.nifs(organizationId),
    queryFn: () =>
      fetchWithAuth<Schemas["OrganizationNifsOut"]>(`/api/v1/organizations/${organizationId}/nifs`),
    enabled: activo && conOrganizacion && gestiona,
    staleTime: STALE,
  });

  const reglas = useQuery({
    queryKey: watchlistKeys.rules,
    queryFn: () => apiGet("/api/v1/watchlist/rules").then((datos) => datos.items ?? []),
    enabled: activo,
    staleTime: STALE,
  });

  const pursuits = useQuery({
    queryKey: [...pursuitKeys.list({}), organizationId],
    queryFn: () =>
      apiGet("/api/v1/pursuits", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    // Sin la organización resuelta se preguntaría por la personal por defecto,
    // que es otra respuesta: se espera a saber contra cuál se pregunta. La
    // espera la expresa ya el propio id, que además adelanta una elección
    // guardada sin aguardar al listado.
    enabled: activo && organizacionResuelta(organizationId),
    staleTime: STALE,
  });

  // Sin organización resuelta todavía, cargando; sin ninguna (`null`) o con el
  // listado roto no hay contra quién preguntar: sin comprobar.
  const perfil: SenalPaso =
    organizations.isError || organizationId === null
      ? "error"
      : !conOrganizacion
        ? "cargando"
        : senalDe(capacidad, (datos) => !faltaCapacidad(datos));
  const nif: SenalPaso = rol === undefined ? "cargando" : gestiona ? senalDe(nifs, hayNif) : "error";

  return {
    capacidad: senalCapacidad(perfil, nif),
    alerta: senalDe(reglas, hayRegla),
    // Si el listado de organizaciones falla, el de pursuits nunca llega a
    // pedirse: quedaría en «cargando» para siempre, que es mentira.
    pursuit: organizations.isError ? "error" : senalDe(pursuits, tienePursuits),
  };
}
