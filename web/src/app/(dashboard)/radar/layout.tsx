import type { Metadata } from "next";
import { PrefetchServidor } from "@/components/prefetch-servidor";
import { consultasRadar } from "./_lib/prefetch";

export const metadata: Metadata = {
  title: "Radar",
};

/**
 * El prefetch del Radar vive aquí y no en `page.tsx` porque ninguna de sus
 * consultas depende de la URL (ver `_lib/prefetch.ts`): el layout no recibe
 * `searchParams` y no le hacen falta. La página sigue siendo el componente
 * cliente de siempre.
 */
export default function RadarLayout({ children }: { children: React.ReactNode }) {
  return <PrefetchServidor consultas={consultasRadar()}>{children}</PrefetchServidor>;
}
