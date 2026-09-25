import type { Metadata } from "next";
import { metadatosHubCpv, paginaHubCpv } from "@/app/(publico)/_components/hub-cpv";

/**
 * Hub por código CPV: la página 1.
 *
 * El contenido vive en `_components/hub-cpv.tsx`, que comparte con las páginas
 * 2 en adelante (`hub-paginado/cpv/[codigo]/[pagina]`, donde el proxy reescribe
 * `?p=N`). Esta ruta ya no mira la query: `/cpv/72?p=1` o con un `p` inválido
 * es esta misma página, como antes, y es lo que le permite servirse desde la
 * caché ISR en vez de renderizarse en cada visita.
 */

type Params = { codigo: string };

/**
 * Ningún código se genera en el build; cada uno se genera y se cachea en su
 * primera visita (ISR en runtime: `generate-static-params.md`, «All paths at
 * runtime», con `dynamicParams` en su `true` por defecto).
 */
export async function generateStaticParams(): Promise<Params[]> {
  return [];
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { codigo } = await params;
  return metadatosHubCpv(codigo, 1);
}

export default async function HubCpv({ params }: { params: Promise<Params> }) {
  const { codigo } = await params;
  return paginaHubCpv(codigo, 1);
}

export const revalidate = 3600;
