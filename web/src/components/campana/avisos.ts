"use client";

/**
 * La bandeja de la campana: consultas, lectura y destino de cada aviso.
 *
 * La campana enseña **solo lo tuyo** (decisión de producto del 2026-10-12):
 * lo que el canal `in_app` del outbox y los productores directos dejan para ti
 * en la organización activa —alertas de tus reglas, cambios en lo que sigues,
 * menciones, tareas y plazos de tus oportunidades, avisos de tu organización—.
 * Las novedades del mercado, sus contadores y el SSE de licitaciones nuevas
 * salieron de aquí: no son de nadie en concreto y las cubre el Resumen.
 *
 * Vive aparte del componente porque lo comparten la vista previa del menú y el
 * panel «Ver todas», y porque así se prueba sin montar el menú de Radix.
 *
 * Llamadas directas y no los hooks de otros espacios (`use-mi-watchlist`,
 * `use-radar`): la campana está en todas las pantallas, y arrastrar esos
 * módulos al bundle común por un par de botones encarece la primera carga de
 * cada ruta.
 */

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { organizacionResuelta, type OrganizacionActiva } from "@/hooks/use-organization";
import { watchlistKeys } from "@/lib/query-keys";

export type Aviso = Schemas["AlertItem"];
export type PaginaAvisos = Schemas["AlertasPagina"];
export type EstadoLectura = "todas" | "sin_leer" | "leidas";

/** Cuántos avisos enseña el menú; el resto, en «Ver todas». */
export const AVISOS_EN_VISTA_PREVIA = 8;
/** Tamaño de página de «Ver todas». */
export const AVISOS_POR_PAGINA = 20;

/**
 * Raíz de las claves de la campana. Empieza por `notifications` a propósito:
 * `providers.tsx` vuelve a pedir ese prefijo al volver a la pestaña, porque el
 * número del distintivo es lo primero que se mira.
 */
export const CLAVE_CAMPANA = ["notifications"] as const;

export const avisosKeys = {
  pagina: (organizationId: OrganizacionActiva, estado: EstadoLectura, limit: number, offset: number) =>
    [...CLAVE_CAMPANA, "alertas", organizationId ?? null, estado, limit, offset] as const,
};

/** Una página de la bandeja de la organización activa. */
export function useAvisos(
  organizationId: OrganizacionActiva,
  {
    estado = "todas",
    limit = AVISOS_EN_VISTA_PREVIA,
    offset = 0,
    refetchInterval,
    enabled = true,
  }: {
    estado?: EstadoLectura;
    limit?: number;
    offset?: number;
    refetchInterval?: number;
    enabled?: boolean;
  } = {},
) {
  return useQuery({
    queryKey: avisosKeys.pagina(organizationId, estado, limit, offset),
    queryFn: ({ signal }) =>
      apiGet("/api/v1/notifications/alerts", {
        params: {
          query: { organization_id: organizationId ?? undefined, estado, limit, offset },
        },
        signal,
      }),
    // Preguntar antes de saber la organización sería preguntar por la personal
    // y pintar un distintivo que no es el de la organización que se mira.
    enabled: enabled && organizacionResuelta(organizationId),
    refetchInterval,
    // Que la campana no conteste no es motivo de toast en cada pantalla: el
    // panel «Ver todas» pinta su error en línea, y el menú sigue usable.
    meta: { silent: true },
  });
}

/**
 * Pinta como leídos los avisos de todas las páginas en caché, antes de que
 * conteste el servidor: el punto azul y el número tienen que reaccionar al clic,
 * no a la vuelta de la red. La invalidación posterior trae la verdad.
 */
function marcarEnCache(queryClient: QueryClient, ids: ReadonlySet<number> | "todos") {
  queryClient.setQueriesData<PaginaAvisos>({ queryKey: [...CLAVE_CAMPANA, "alertas"] }, (pagina) => {
    if (!pagina) return pagina;
    let recienLeidos = 0;
    const items = pagina.items.map((aviso) => {
      if (aviso.read || (ids !== "todos" && !ids.has(aviso.id))) return aviso;
      recienLeidos += 1;
      return { ...aviso, read: true };
    });
    const sinLeer = ids === "todos" ? 0 : Math.max(0, pagina.sin_leer - recienLeidos);
    return { ...pagina, items, sin_leer: sinLeer };
  });
}

/**
 * Marcar como leído: un aviso al abrirlo, o todos con la acción explícita.
 *
 * `organization_id` viaja siempre: sin él el servidor resuelve la organización
 * personal y la marca no tocaría los avisos que se están viendo.
 */
export function useMarcarLeidos(organizationId: OrganizacionActiva) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (objetivo: { ids: number[] } | "todos") =>
      apiMutate("POST", "/api/v1/notifications/alerts/read", {
        ...(objetivo === "todos" ? { all: true } : { ids: objetivo.ids }),
        organization_id: organizationId ?? undefined,
      }),
    onMutate: (objetivo) => {
      marcarEnCache(queryClient, objetivo === "todos" ? "todos" : new Set(objetivo.ids));
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: [...CLAVE_CAMPANA, "alertas"] }),
    meta: { errorTitle: "No se pudo marcar como leído" },
  });
}

/**
 * `type` de los avisos de caducidad de la documentación acreditativa
 * (`organizacion.documento_caduca` en `shared/events.py`). No traen expediente:
 * su sitio es el perfil de capacidad de la organización.
 */
export const TIPO_DOCUMENTACION_CADUCA = "documentacion_caduca";

/**
 * A dónde lleva abrir un aviso, o `null` si no tiene destino propio.
 *
 * Si el expediente ya es una oportunidad del equipo, el destino útil es su
 * ficha —donde está la decisión y el cierre—, no el inspector del catálogo.
 */
export function destinoDeAviso(aviso: Aviso): string | null {
  if (aviso.pursuit_id != null) return `/oportunidades/${aviso.pursuit_id}`;
  if (aviso.licitacion_id) return `/detalle?lic=${encodeURIComponent(aviso.licitacion_id)}`;
  if (aviso.type.startsWith(TIPO_DOCUMENTACION_CADUCA)) return "/equipo?tab=organizacion";
  return null;
}

type Regla = Schemas["WatchlistRuleOut"];
/**
 * Cuerpo del `PUT` sin `visibility`: la actualización no la escribe
 * (`services/watchlist_rules.update_rule`), y el listado la rellena con el
 * valor por defecto en vez de leerla, así que reenviarla no diría nada cierto.
 */
type CuerpoRegla = Omit<Schemas["WatchlistRuleBody"], "visibility">;

/** Lo que `PUT /watchlist/rules/{id}` necesita para no tocar los criterios. */
function cuerpoDe(regla: Regla, activa: boolean, organizationId: OrganizacionActiva): CuerpoRegla {
  return {
    nombre: regla.nombre ?? null,
    keyword: regla.keyword ?? null,
    cpv: regla.cpv ?? null,
    min_importe: regla.min_importe ?? null,
    ccaa: regla.ccaa ?? null,
    frequency: regla.frequency,
    tecnologia: regla.tecnologia ?? null,
    organo: regla.organo ?? null,
    procedimiento: regla.procedimiento ?? null,
    tipo_contrato: regla.tipo_contrato ?? null,
    banda_min: regla.banda_min ?? null,
    plazo_min_dias: regla.plazo_min_dias ?? null,
    active: activa,
    organization_id: organizationId ?? null,
  };
}

export type ResultadoPausa = "hecho" | "no_existe" | "sin_cambio";

/**
 * Pone en pausa (o reactiva) la regla que disparó una alerta, con el endpoint
 * de reglas de siempre.
 *
 * `PUT /watchlist/rules/{id}` reemplaza los criterios, así que primero se lee
 * la regla tal cual está: mandar solo `active` borraría la palabra clave, el
 * CPV y el resto. No hay lectura de una regla suelta, y por eso se pide el
 * listado (una consulta, el mismo que abre Mi Watchlist); cuesta una petición
 * más, y solo cuando alguien pulsa el botón.
 */
export async function cambiarActivaRegla(
  ruleId: number,
  activa: boolean,
  organizationId: OrganizacionActiva,
): Promise<ResultadoPausa> {
  const { items } = await apiGet("/api/v1/watchlist/rules", {
    params: { query: { organization_id: organizationId ?? undefined } },
  });
  const regla = items.find((r) => r.id === ruleId);
  if (!regla) return "no_existe";
  if (regla.active === activa) return "sin_cambio";
  await apiMutate("PUT", `/api/v1/watchlist/rules/${ruleId}`, cuerpoDe(regla, activa, organizationId));
  return "hecho";
}

/** Tras pausar o reactivar: Mi Watchlist y el onboarding leen el mismo listado. */
export function refrescarReglas(queryClient: QueryClient) {
  return queryClient.invalidateQueries({ queryKey: watchlistKeys.rules });
}
