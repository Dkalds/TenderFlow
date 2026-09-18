import { HydrationBoundary } from "@tanstack/react-query";
import { prefetchEnServidor, type ConsultaServidor } from "@/lib/server-prefetch";

/**
 * Server Component: pide `consultas` durante el render de servidor y entrega el
 * resultado al `QueryClient` del navegador. Lo que envuelve no cambia: sus
 * hooks encuentran la clave en caché. Reglas y límites en
 * `lib/server-prefetch.ts`; el patrón, en `web/AGENTS.md`.
 */
export async function PrefetchServidor({
  consultas,
  children,
}: {
  consultas: readonly ConsultaServidor[];
  children: React.ReactNode;
}) {
  const estado = await prefetchEnServidor(consultas);
  return <HydrationBoundary state={estado}>{children}</HydrationBoundary>;
}
