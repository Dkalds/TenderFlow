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

  const { data: keysData, isLoading } = useQuery<ApiKeysResponse>({
    queryKey: adminKeys.apiKeys,
    queryFn: () => fetchWithAuth<ApiKeysResponse>("/api/v1/me/keys"),
  });

  const rotateKey = useMutation({
    mutationFn: () =>
      apiMutate<{ raw_token?: string; token?: string }>("POST", "/api/v1/me/keys/rotate"),
    onSuccess: (data) => {
      const token = data.raw_token ?? data.token ?? "???";
      setNewKeyToken(token);
      queryClient.invalidateQueries({ queryKey: adminKeys.apiKeys });
    },
    onError: () => {
      toast.error("Error al generar clave. Intenta de nuevo.");
    },
  });

  return {
    apiKeys: keysData?.keys ?? keysData?.items ?? [],
    isLoading,
    rotateKey,
    newKeyToken,
    clearNewKeyToken: () => setNewKeyToken(null),
  };
}
