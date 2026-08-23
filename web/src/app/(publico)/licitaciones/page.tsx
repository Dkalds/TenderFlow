import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { obtenerHubs } from "@/lib/publico-api";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { listaJsonLd, migasJsonLd } from "@/lib/jsonld";
import { rutaHubCcaa } from "@/lib/slug";
import { formatNumber } from "@/lib/utils";

/**
 * Índice de la superficie de licitaciones, por comunidad autónoma.
 *
 * Es el nodo que faltaba. Sin él pasaban dos cosas: `/licitaciones` devolvía
 * 404 —pese a que `robots.txt` abre ese prefijo y a que borrar el último
 * segmento de una URL es comportamiento normal de usuario— y, sobre todo, los
 * hubs por comunidad no recibían **ningún enlace interno**: existían en el
 * sitemap, así que Google los rastreaba, pero nada les transmitía autoridad. Un
 * sitemap dice "existo"; los enlaces dicen "importo".
 */

export const metadata: Metadata = {
  title: "Licitaciones públicas de tecnología en España",
  description:
    "Concursos públicos de tecnología por comunidad autónoma: objeto, órgano de contratación, presupuesto y plazos, con enlace al anuncio oficial.",
  alternates: { canonical: "/licitaciones" },
  openGraph: {
    ...OG_IMAGE_COMPARTIDA,
    title: "Licitaciones públicas de tecnología en España",
    description: "Concursos públicos de tecnología por comunidad autónoma.",
    url: "/licitaciones",
  },
  twitter: {
    ...TWITTER_COMPARTIDO,
    title: "Licitaciones públicas de tecnología en España",
    description: "Concursos públicos de tecnología por comunidad autónoma.",
  },
};

export const revalidate = 3600;

export default async function IndiceLicitaciones() {
  const { ccaa } = await obtenerHubs();

  // Un índice sin nada que indexar es contenido delgado. Mejor 404 que una
  // página vacía que Google cuente contra la calidad del dominio.
  if (ccaa.length === 0) notFound();

  const migas = [
    { nombre: "Inicio", ruta: "/" },
    { nombre: "Licitaciones", ruta: "/licitaciones" },
  ];
  const entradas = ccaa.map((hub) => ({ titulo: hub.nombre, ruta: rutaHubCcaa(hub.slug) }));

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify([migasJsonLd(migas), listaJsonLd("Licitaciones por comunidad autónoma", entradas)]),
        }}
      />

      <div className="mx-auto w-full max-w-5xl px-6 py-12">
        <h1 className="font-display text-3xl font-bold tracking-[-0.025em] text-balance md:text-4xl">
          Licitaciones públicas de tecnología en España
        </h1>
        <p className="text-muted-foreground mt-4 max-w-[62ch] text-base leading-relaxed">
          Concursos con componente de tecnología enterprise publicados por la administración española, agrupados por
          comunidad autónoma. Los datos proceden de la Plataforma de Contratación del Sector Público y de TED, y cada
          ficha enlaza al anuncio original.
        </p>

        <h2 className="font-display mt-12 text-xl font-semibold tracking-[-0.02em]">Por comunidad autónoma</h2>
        <ul className="mt-5 grid gap-x-8 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
          {ccaa.map((hub) => (
            <li key={hub.slug}>
              <Link
                href={rutaHubCcaa(hub.slug)}
                className="hover:bg-accent/60 flex items-baseline justify-between gap-3 rounded px-1 py-2"
              >
                <span className="text-sm font-medium">{hub.nombre}</span>
                <span className="text-muted-foreground text-xs tabular-nums">{formatNumber(hub.total)}</span>
              </Link>
            </li>
          ))}
        </ul>

        <p className="text-muted-foreground mt-10 text-sm">
          ¿Buscas por tipo de contrato?{" "}
          <Link href="/cpv" className="text-foreground font-medium underline underline-offset-4">
            Índice por código CPV
          </Link>
          .
        </p>
      </div>
    </>
  );
}
