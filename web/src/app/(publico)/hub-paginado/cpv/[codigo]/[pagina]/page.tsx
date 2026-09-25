import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { metadatosHubCpv, paginaHubCpv } from "@/app/(publico)/_components/hub-cpv";
import { paginaDeSegmento } from "@/lib/paginacion-hubs";

/**
 * Páginas 2 en adelante del hub por código CPV: `/cpv/{codigo}?p=N`.
 *
 * Ruta interna. El proxy reescribe aquí `?p=N` y contesta 404 a quien pida esta
 * ruta directamente, así que su única URL pública es la de la query, que es la
 * que declaran el canonical y la paginación. Recibir el número por `params` en
 * vez de leer la query es lo que deja cada página en su propia entrada de la
 * caché ISR (ver `lib/paginacion-hubs.ts`).
 */

type Params = { codigo: string; pagina: string };

/** Nada en el build: cada página se genera y se cachea en su primera visita. */
export async function generateStaticParams(): Promise<Params[]> {
  return [];
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { codigo, pagina } = await params;
  return metadatosHubCpv(codigo, paginaDeSegmento(pagina) ?? notFound());
}

export default async function HubCpvPaginado({ params }: { params: Promise<Params> }) {
  const { codigo, pagina } = await params;
  return paginaHubCpv(codigo, paginaDeSegmento(pagina) ?? notFound());
}

export const revalidate = 3600;
