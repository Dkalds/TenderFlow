"use client";

/**
 * Claves de API de la cuenta y rotación.
 *
 * El token en claro solo viaja en la respuesta de la rotación: se guarda en
 * estado para enseñarlo una vez y no vuelve a existir en ningún sitio.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { adminKeys } from "@/lib/query-keys";

export interface ApiKey {
  prefix?: string;
  key_prefix?: string;
  created_at?: string;
  last_used?: string;
  scopes?: string[];
  active?: boolean;
}

interface ApiKeysResponse {
  keys?: ApiKey[];
  items?: ApiKey[];
}

export function useApiKeys() {
  const queryClient = useQueryClient();
  const [newKeyToken, setNewKeyToken] = useState<string | null>(null);

  const {
    data: keysData,
    isLoading,
    error,
    refetch,
  } = useQuery<ApiKeysResponse>({
    queryKey: adminKeys.apiKeys,
    queryFn: () => fetchWithAuth<ApiKeysResponse>("/api/v1/me/keys"),
    // El fallo lo pinta la tarjeta (`PanelError`): sin toast encima, y sin
    // caer al vacío «no hay claves», que afirmaría algo que nadie ha leído.
    meta: META_ERROR_EN_LINEA,
  });

  const rotateKey = useMutation({
    mutationFn: () =>
      apiMutate<{ raw_token?: string; token?: string }>("POST", "/api/v1/me/keys/rotate"),
    onSuccess: (data) => {
      const token = data.raw_token ?? data.token;
      // Sin valor no hay nada que enseñar: pintar «???» como si fuera la clave
      // era peor que decirlo.
      if (token) setNewKeyToken(token);
      else toast.error("La clave se generó, pero no llegó su valor. Genera otra para poder copiarla.");
      queryClient.invalidateQueries({ queryKey: adminKeys.apiKeys });
    },
    onError: () => {
      toast.error("No se pudo generar la clave. Vuelve a intentarlo.");
    },
  });

  return {
    apiKeys: keysData?.keys ?? keysData?.items ?? [],
    isLoading,
    error,
    refetch: () => void refetch(),
    rotateKey,
    newKeyToken,
    clearNewKeyToken: () => setNewKeyToken(null),
  };
}
