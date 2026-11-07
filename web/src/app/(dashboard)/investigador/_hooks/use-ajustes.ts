"use client";

/**
 * Lo que la consola del Investigador recuerda: los ajustes de «Opciones
 * avanzadas» (en este navegador) y las consultas recientes (en la cuenta).
 *
 * Las consultas recientes viven en servidor (`/api/v1/me/consultas-recientes`)
 * desde 2026-11: antes solo estaban en el `localStorage` de cada navegador y
 * no viajaban a otro dispositivo. `localStorage` sigue siendo su caché —se ve
 * la lista al instante, y si la API no responde se queda la última conocida— y
 * la primera vez que la cuenta llega vacía se sube lo que este navegador
 * recordaba, una sola vez.
 *
 * Se lee de `localStorage` **tras el montaje**, nunca durante el render: leerlo
 * antes rompía la hidratación. `lista` dice cuándo ya se leyó, para que quien
 * busca espere a los ajustes guardados en vez de pedir primero con los de por
 * defecto y otra vez con los suyos.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { investigadorKeys } from "@/lib/query-keys";
import {
  DEFAULT_CONFIG,
  MAX_HISTORY,
  historialSubido,
  loadConfig,
  loadHistory,
  marcarHistorialSubido,
  saveConfig,
  saveHistory,
} from "../_lib/config-storage";
import type { InvestigadorConfig } from "../_lib/types";

type ConsultasRecientes = Schemas["ConsultasRecientes"];

const RUTA = "/api/v1/me/consultas-recientes";

export interface AjustesInvestigador {
  config: InvestigadorConfig;
  /** Los ajustes guardados ya se han leído. */
  lista: boolean;
  updateConfig: (patch: Partial<InvestigadorConfig>) => void;
  history: string[];
  addHistory: (consulta: string) => void;
}

/** `consulta` arriba, sin repetirla, con el tope de la lista. */
export function arriba(consulta: string, lista: readonly string[]): string[] {
  return [consulta, ...lista.filter((h) => h !== consulta)].slice(0, MAX_HISTORY);
}

function apuntar(consulta: string): Promise<ConsultasRecientes> {
  return apiMutate<ConsultasRecientes>("POST", RUTA, { consulta });
}

export function useAjustes(): AjustesInvestigador {
  const queryClient = useQueryClient();
  const [cache, setCache] = useState<string[]>([]);
  // Para `addHistory`, que tiene que ser estable: `use-investigador` lo llama
  // desde un efecto que depende de él.
  const cacheRef = useRef<string[]>([]);
  const [config, setConfig] = useState<InvestigadorConfig>(DEFAULT_CONFIG);
  const [lista, setLista] = useState(false);

  useEffect(() => {
    cacheRef.current = loadHistory();
    setCache(cacheRef.current);
    setConfig(loadConfig());
    setLista(true);
  }, []);

  // Un fallo no se anuncia: la lista que se ve es la de la caché.
  const servidor = useQuery({
    queryKey: investigadorKeys.historial,
    queryFn: () => apiGet(RUTA),
    meta: META_ERROR_EN_LINEA,
  });
  const delServidor = servidor.data?.consultas;

  const subiendo = useRef(false);
  useEffect(() => {
    if (!delServidor || !lista || subiendo.current) return;
    if (delServidor.length === 0 && cache.length > 0 && !historialSubido()) {
      // La primera vez, lo que recordaba este navegador pasa a la cuenta, de la
      // más antigua a la más reciente para conservar el orden. Si falla, se
      // reintenta en la próxima visita: la caché no se ha tocado.
      subiendo.current = true;
      void [...cache]
        .reverse()
        .reduce<Promise<ConsultasRecientes | null>>((previa, c) => previa.then(() => apuntar(c)), Promise.resolve(null))
        .then((final) => {
          marcarHistorialSubido();
          if (final) queryClient.setQueryData(investigadorKeys.historial, final);
        })
        .catch(() => undefined)
        .finally(() => {
          subiendo.current = false;
        });
      return;
    }
    marcarHistorialSubido();
    cacheRef.current = delServidor;
    saveHistory(delServidor);
  }, [delServidor, cache, lista, queryClient]);

  const updateConfig = useCallback((patch: Partial<InvestigadorConfig>) => {
    setConfig((prev) => {
      const next = { ...prev, ...patch };
      saveConfig(next);
      return next;
    });
  }, []);

  const { mutate } = useMutation({
    mutationFn: apuntar,
    onSuccess: (data) => queryClient.setQueryData(investigadorKeys.historial, data),
    meta: META_ERROR_EN_LINEA,
  });

  const addHistory = useCallback(
    (consulta: string) => {
      // Se ve al momento; la respuesta del servidor la sustituye (normaliza espacios).
      queryClient.setQueryData<ConsultasRecientes>(investigadorKeys.historial, (previa) => ({
        consultas: arriba(consulta, previa?.consultas ?? cacheRef.current),
      }));
      cacheRef.current = arriba(consulta, cacheRef.current);
      saveHistory(cacheRef.current);
      setCache(cacheRef.current);
      mutate(consulta);
    },
    [queryClient, mutate],
  );

  return { config, lista, updateConfig, history: delServidor ?? cache, addHistory };
}
