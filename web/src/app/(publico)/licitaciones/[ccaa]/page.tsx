import type { Metadata } from "next";
import { metadatosHubCcaa, paginaHubCcaa } from "@/app/(publico)/_components/hub-ccaa";

/**
 * Hub de licitaciones por comunidad autónoma: la página 1.
 *
 * El contenido vive en `_components/hub-ccaa.tsx`, que comparte con las páginas
 * 2 en adelante (`hub-paginado/licitaciones/[ccaa]/[pagina]`, donde el proxy
 * reescribe `?p=N`). Esta ruta ya no mira la query: `/licitaciones/madrid?p=1`
 * o con un `p` inválido es esta misma página, como antes, y es lo que le
 * permite servirse desde la caché ISR en vez de renderizarse en cada visita.
 */

type Params = { ccaa: string };

/**
 * Ninguna comunidad se genera en el build; cada una se genera y se cachea en su
 * primera visita. Es la forma documentada de pedir ISR en una ruta dinámica
 * («All paths at runtime» en `generate-static-params.md`, con `dynamicParams`
 * en su `true` por defecto): sin esta función la ruta se renderizaba en cada
 * petición aunque declarase `revalidate`.
 */
export async function generateStaticParams(): Promise<Params[]> {
  return [];
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { ccaa } = await params;
  return metadatosHubCcaa(ccaa, 1);
}

export default async function HubCcaa({ params }: { params: Promise<Params> }) {
  const { ccaa } = await params;
  return paginaHubCcaa(ccaa, 1);
}

export const revalidate = 3600;
