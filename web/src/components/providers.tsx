"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { SessionProvider } from "@/lib/auth";
import { MotionProvider } from "@/components/motion";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
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
          <MotionProvider>
            <NuqsAdapter>{children}</NuqsAdapter>
          </MotionProvider>
        </SessionProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
