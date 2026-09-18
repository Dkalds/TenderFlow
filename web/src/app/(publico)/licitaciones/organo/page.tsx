import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowUpRight, Landmark } from "lucide-react";
import { hubsOrganoAnunciables, obtenerHubs } from "@/lib/publico-api";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { listaJsonLd, migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaHubOrgano } from "@/lib/slug";
import { formatNumber } from "@/lib/utils";

/**
 * Índice de hubs por órgano de contratación (F6.5).
 *
 * Existe por lo mismo que `/licitaciones`: un hub que sólo está en el sitemap
 * se rastrea, pero nada le transmite autoridad. Lista los mismos órganos que
 * el sitemap —los de más de diez anuncios, `hubsOrganoAnunciables`— para que
 * índice y sitemap no anuncien cosas distintas. Totales del backend (ADR-014).
 */

const TITULO = "Licitaciones por órgano de contratación";
const DESCRIPCION =
  "Concursos públicos de tecnología agrupados por el órgano que los publica: ayuntamientos, consejerías, ministerios y entidades públicas.";

export const metadata: Metadata = {
  title: TITULO,
  description: DESCRIPCION,
  alternates: { canonical: "/licitaciones/organo" },
  openGraph: { ...OG_IMAGE_COMPARTIDA, title: TITULO, description: DESCRIPCION, url: "/licitaciones/organo" },
  twitter: { ...TWITTER_COMPARTIDO, title: TITULO, description: DESCRIPCION },
};

export const revalidate = 3600;

export default async function IndiceOrganos() {
  const organos = hubsOrganoAnunciables(await obtenerHubs());
  // Sin órganos con volumen no hay índice: contenido delgado, 404.
  if (organos.length === 0) notFound();

  const migas = [
    { nombre: "Inicio", ruta: "/" },
    { nombre: "Licitaciones", ruta: "/licitaciones" },
    { nombre: "Órganos de contratación", ruta: "/licitaciones/organo" },
  ];
  const entradas = organos.map((hub) => ({ titulo: hub.nombre, ruta: rutaHubOrgano(hub.slug) }));

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: serializarJsonLd([migasJsonLd(migas), listaJsonLd(TITULO, entradas)]) }}
      />

      <div className="mx-auto w-full max-w-6xl px-6 py-12">
        <p className="text-primary flex items-center gap-2 font-mono text-xs tracking-widest uppercase">
          <Landmark className="h-4 w-4" aria-hidden="true" />
          Por órgano de contratación
        </p>
        <h1 className="font-display mt-3 text-3xl font-bold tracking-[-0.025em] text-balance md:text-4xl">{TITULO}</h1>
        <p className="text-muted-foreground mt-4 max-w-[62ch] text-base leading-relaxed">{DESCRIPCION}</p>

        <ul className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {organos.map((hub) => (
            <li key={hub.slug}>
              <Link
                href={rutaHubOrgano(hub.slug)}
                className="group border-border/70 bg-card focus-visible:ring-ring hover:border-primary/40 flex items-center justify-between gap-3 rounded-xl border px-5 py-4 transition-[transform,border-color,box-shadow] duration-200 ease-out hover:shadow-md focus-visible:ring-2 focus-visible:outline-none active:scale-[0.99]"
              >
                <span className="min-w-0">
                  <span className="line-clamp-2 block text-sm font-semibold">{hub.nombre}</span>
                  <span className="text-muted-foreground tf-tnum mt-0.5 block text-xs">
                    {formatNumber(hub.total)} licitaciones
                  </span>
                </span>
                <ArrowUpRight
                  aria-hidden="true"
                  className="text-muted-foreground group-hover:text-primary h-4 w-4 shrink-0 transition-[transform,color] duration-200 ease-out group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                />
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
