"use client";

import * as React from "react";
import { QueryCache, MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { SessionProvider } from "@/lib/auth";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  notifyQueryError,
  notifyMutationError,
  notifyMutationSuccess,
  debeReintentar,
  retrasoDeReintento,
  type QueryFeedbackMeta,
} from "@/lib/query-feedback";

export function Providers({ children, nonce }: { children: React.ReactNode; nonce?: string }) {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({
          onError: (error, query) => notifyQueryError(error, query.meta as QueryFeedbackMeta | undefined),
        }),
        mutationCache: new MutationCache({
          onError: (error, _vars, _ctx, mutation) =>
            notifyMutationError(error, mutation.meta as QueryFeedbackMeta | undefined),
          onSuccess: (_data, _vars, _ctx, mutation) =>
            notifyMutationSuccess(mutation.meta as QueryFeedbackMeta | undefined),
        }),
        defaultOptions: {
          queries: {
            staleTime: 5 * 60 * 1000,
            /*
             * Política de reintentos centralizada (`lib/query-feedback.ts`), no
             * repartida hook a hook. Era `retry: 1` para todo: un 404 se pedía
             * dos veces y un arranque en frío de la API —Render free con
             * spin-down— se daba por perdido tras un único reintento inmediato.
             * Ahora solo se reintenta lo que puede cambiar de resultado (red,
             * 408, 5xx) y con backoff creciente.
             */
            retry: debeReintentar,
            retryDelay: retrasoDeReintento,
          },
          /*
           * Las mutaciones se quedan sin reintento (default de React Query): no
           * son idempotentes y repetir un POST puede duplicar un efecto.
           */
        },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      {/* `system` como default: quien no ha elegido tema sigue al del sistema
          operativo — relevante sobre todo para la superficie pública, donde el
          visitante anónimo no tiene toggle. Una elección explícita (toggle del
          menú de cuenta / paleta) se persiste y gana. Todo consumidor que
          decida algo por tema debe leer `resolvedTheme`, no `theme`: con
          default system, `theme` vale "system". */}
      <ThemeProvider attribute="class" defaultTheme="system" disableTransitionOnChange nonce={nonce}>
        <SessionProvider>
          <TooltipProvider>
            <NuqsAdapter>{children}</NuqsAdapter>
          </TooltipProvider>
        </SessionProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
