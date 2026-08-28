import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowUpRight, MapPin } from "lucide-react";
import { obtenerHubs } from "@/lib/publico-api";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { listaJsonLd, migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
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
 *
 * Los totales por comunidad vienen del endpoint de hubs: aquí no se cuenta
 * nada (ADR-014), solo se pinta con el mismo lenguaje visual de la landing.
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
  //
  // La condición dice lo que parece **desde que `obtenerHubs` distingue "no hay
  // hubs" de "no pude preguntar"** (ver `lib/publico-api.ts`). Antes no: un
  // fallo de red devolvía la misma lista vacía, y como esta ruta es ISR, la
  // revalidación que pillaba la API fría sustituía el índice bueno por un 404
  // que se servía durante la hora siguiente. Ahora ese caso lanza: la
  // regeneración falla, Next conserva la copia anterior y lo reintenta. Este
  // `notFound()` solo se ejecuta cuando el backend afirmó que no hay hubs.
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
          __html: serializarJsonLd([migasJsonLd(migas), listaJsonLd("Licitaciones por comunidad autónoma", entradas)]),
        }}
      />

      <div className="mx-auto w-full max-w-6xl px-6 py-12">
        <p className="text-primary flex items-center gap-2 font-mono text-xs tracking-widest uppercase">
          <MapPin className="h-4 w-4" aria-hidden="true" />
          Por comunidad autónoma
        </p>
        <h1 className="font-display mt-3 text-3xl font-bold tracking-[-0.025em] text-balance md:text-4xl">
          Licitaciones públicas de tecnología en España
        </h1>
        <p className="text-muted-foreground mt-4 max-w-[62ch] text-base leading-relaxed">
          Concursos con componente de tecnología enterprise publicados por la administración española, agrupados por
          comunidad autónoma. Los datos proceden de la Plataforma de Contratación del Sector Público y de TED, y cada
          ficha enlaza al anuncio original.
        </p>

        <ul className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ccaa.map((hub) => (
            <li key={hub.slug}>
              <Link
                href={rutaHubCcaa(hub.slug)}
                className="group border-border/70 bg-card focus-visible:ring-ring hover:border-primary/40 flex items-center justify-between gap-3 rounded-xl border px-5 py-4 transition-[transform,border-color,box-shadow] duration-200 ease-out hover:shadow-md focus-visible:ring-2 focus-visible:outline-none active:scale-[0.99]"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold">{hub.nombre}</span>
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
