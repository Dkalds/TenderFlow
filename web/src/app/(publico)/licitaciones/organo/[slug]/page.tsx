import type { Metadata } from "next";
import { metadatosHubOrgano, paginaHubOrgano } from "@/app/(publico)/_components/hub-organo";

/**
 * Hub público por órgano de contratación (F6.5): la página 1.
 *
 * El contenido vive en `_components/hub-organo.tsx`, que comparte con las
 * páginas 2 en adelante (`hub-paginado/licitaciones/organo/[slug]/[pagina]`,
 * donde el proxy reescribe `?p=N`). Esta ruta ya no mira la query, y es lo que
 * le permite servirse desde la caché ISR en vez de renderizarse en cada visita.
 */

type Params = { slug: string };

/**
 * Ningún órgano se genera en el build; cada uno se genera y se cachea en su
 * primera visita (ISR en runtime: `generate-static-params.md`, «All paths at
 * runtime», con `dynamicParams` en su `true` por defecto).
 */
export async function generateStaticParams(): Promise<Params[]> {
  return [];
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { slug } = await params;
  return metadatosHubOrgano(slug, 1);
}

export default async function HubOrgano({ params }: { params: Promise<Params> }) {
  const { slug } = await params;
  return paginaHubOrgano(slug, 1);
}

export const revalidate = 3600;
