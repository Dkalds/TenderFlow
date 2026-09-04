"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api-client";
import { pursuitKeys } from "@/hooks/use-pursuits";
import { useActiveOrganizationId, useOrganizations } from "@/hooks/use-organization";
import { hayReglaActiva, perfilConfigurado, tienePursuits } from "@/components/onboarding/senales";
import type { PasoId, SenalPaso } from "@/components/onboarding/pasos";
import { perfilKeys, watchlistKeys } from "@/lib/query-keys";

/**
 * De qué dato del servidor sale cada primer paso.
 *
 * No hay endpoint de onboarding y no lo va a haber: un campo
 * `onboarding_completado` pediría una migración (prohibida) para guardar algo
 * que ya es deducible. Los tres pasos se leen de superficies que la API sirve
 * desde hace tiempo:
 *
 * | paso    | endpoint               | «hecho» cuando                    |
 * | ------- | ---------------------- | --------------------------------- |
 * | perfil  | `GET /me/profile`      | el perfil trae algo suyo          |
 * | reglas  | `GET /watchlist/rules` | hay al menos una regla **activa** |
 * | pursuit | `GET /pursuits`        | `total > 0`                       |
 *
 * Las claves de caché son deliberadamente las mismas que usan `mi-perfil`,
 * `mi-watchlist` y `usePursuits`: quien venga de esas pantallas no paga una
 * segunda petición, y un alta hecha allí invalida esto de rebote.
 *
 * `activo` apaga las tres queries de golpe. Un veterano que ya ocultó la banda
 * no debe pagar tres peticiones en la pantalla de entrada para no ver nada.
 */

/** Cinco minutos: nada de esto cambia mientras se mira el Resumen. */
const STALE = 5 * 60_000;

/** Envuelve una query en la señal de tres estados que consume `derivarPasos`. */
function senalDe<T>(
  query: { data: T | undefined; isError: boolean },
  cumple: (data: T) => boolean,
): SenalPaso {
  if (query.isError) return "error";
  if (query.data === undefined) return "cargando";
  return cumple(query.data);
}

export function useSenalesOnboarding(activo: boolean): Partial<Record<PasoId, SenalPaso>> {
  // `useActiveOrganizationId` ya resuelve `["organizations"]`; pedirlo otra vez
  // es gratis (misma clave) y aquí hace falta el estado de esa query, no sólo
  // su resultado, para no colgar los pursuits de un id que aún no existe.
  const organizations = useOrganizations();
  const organizationId = useActiveOrganizationId();

  const perfil = useQuery({
    queryKey: perfilKeys.me,
    queryFn: () => apiGet("/api/v1/me/profile"),
    enabled: activo,
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
    // que es otra respuesta: se espera a saber contra cuál se pregunta.
    enabled: activo && !organizations.isPending,
    staleTime: STALE,
  });

  return {
    perfil: senalDe(perfil, perfilConfigurado),
    reglas: senalDe(reglas, hayReglaActiva),
    // Si el listado de organizaciones falla, el de pursuits nunca llega a
    // pedirse: quedaría en «cargando» para siempre, que es mentira.
    pursuit: organizations.isError ? "error" : senalDe(pursuits, tienePursuits),
  };
}
