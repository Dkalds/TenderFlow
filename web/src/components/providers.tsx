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
import { pursuitKeys } from "@/lib/query-keys";

/**
 * Consultas que sí se vuelven a pedir al volver a la pestaña.
 *
 * El default es no hacerlo (ver `crearQueryClient`). Aquí entra sólo lo que
 * cambia por la mano de otros mientras la pestaña está en segundo plano y cuya
 * versión rancia lleva a actuar mal; todo lo demás espera a su `staleTime` o a
 * una invalidación. Son consultas por organización, pequeñas: nada que recorra
 * el histórico de licitaciones.
 *
 * Se declaran por prefijo de clave (`setQueryDefaults` casa por prefijo) y no
 * en cada hook porque es una política, igual que los reintentos: así se audita
 * en un sitio, y alcanza también a la campana, cuyo componente no es de este
 * módulo. Una opción que ponga el propio hook gana a estos defaults.
 */
export const CLAVES_FRESCAS_AL_VOLVER: readonly (readonly unknown[])[] = [
  // La Agenda: plazos que vencen hoy y tareas que el equipo va cerrando. Es la
  // pantalla a la que se vuelve para saber qué toca ahora.
  pursuitKeys.agenda,
  // La campana (`NOTIFICATIONS_KEY` de `notification-bell.tsx`): su contador es
  // lo primero que se mira al volver. Su `refetchInterval` se pausa con la
  // pestaña oculta, así que sin esto el número podía llevar cinco minutos viejo.
  ["notifications"],
  // Tablero, ficha y tareas de una oportunidad: los mueven varias personas, y
  // el PATCH lleva `expected_version`. Arrastrar una tarjeta sobre un tablero
  // rancio acaba en un 409 y en deshacer el movimiento.
  [...pursuitKeys.all, "list"],
  [...pursuitKeys.all, "detail"],
  [...pursuitKeys.all, "tasks"],
];

/**
 * El `QueryClient` del navegador, con la política común a todas las pantallas.
 *
 * Es una función aparte del componente para poder probar la política sin
 * montar la pila de providers entera.
 */
export function crearQueryClient(): QueryClient {
  const queryClient = new QueryClient({
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
         * 30 min y no los 5 de React Query. Con 5, una pantalla que se
         * abandonaba cinco minutos perdía su caché y volver a ella pintaba
         * esqueletos y relanzaba sus agregados, aunque el dato —que se
         * refresca a diario— fuera el mismo. Lo rancio lo sigue decidiendo
         * `staleTime`: esto sólo evita volver a empezar de cero.
         */
        gcTime: 30 * 60 * 1000,
        /*
         * Apagado por defecto. Cada vuelta a la pestaña relanzaba todas las
         * consultas rancias montadas —en Resumen, siete agregados sobre el
         * histórico entero— contra una API de un solo proceso. Lo que sí
         * necesita estar al día al volver lo enumera `CLAVES_FRESCAS_AL_VOLVER`.
         */
        refetchOnWindowFocus: false,
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
  });
  for (const queryKey of CLAVES_FRESCAS_AL_VOLVER) {
    queryClient.setQueryDefaults(queryKey, { refetchOnWindowFocus: true });
  }
  return queryClient;
}

export function Providers({ children, nonce }: { children: React.ReactNode; nonce?: string }) {
  const [queryClient] = React.useState(crearQueryClient);
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
