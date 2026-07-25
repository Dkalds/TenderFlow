"use client";

import * as React from "react";
import {
  QueryCache,
  MutationCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { SessionProvider } from "@/lib/auth";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  notifyQueryError,
  notifyMutationError,
  notifyMutationSuccess,
  type QueryFeedbackMeta,
} from "@/lib/query-feedback";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({
          onError: (error, query) =>
            notifyQueryError(error, query.meta as QueryFeedbackMeta | undefined),
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
            retry: 1,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider
        attribute="class"
        defaultTheme="dark"
        enableSystem={false}
        disableTransitionOnChange
      >
        <SessionProvider>
          <TooltipProvider>
            <NuqsAdapter>{children}</NuqsAdapter>
          </TooltipProvider>
        </SessionProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
