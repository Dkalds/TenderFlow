import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowUpRight, Hash } from "lucide-react";
import { obtenerHubs } from "@/lib/publico-api";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { listaJsonLd, migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaHubCpv } from "@/lib/slug";
import { formatNumber } from "@/lib/utils";

/**
 * Índice por código CPV.
 *
 * El CPV es el vocabulario común de contratación pública de la UE y buena parte
 * del público objetivo busca literalmente por código. Igual que
 * `/licitaciones`, este índice existe tanto para que la URL padre no devuelva
 * 404 como para que los hubs por código reciban enlaces internos.
 *
 * Los totales por código vienen del endpoint de hubs (ADR-014: aquí no se
 * agrega nada); las cards comparten lenguaje visual con la landing.
 */

export const metadata: Metadata = {
  title: "Licitaciones por código CPV",
  description:
    "Concursos públicos de tecnología agrupados por código CPV, el vocabulario común de contratación pública de la Unión Europea.",
  alternates: { canonical: "/cpv" },
  openGraph: {
    ...OG_IMAGE_COMPARTIDA,
    title: "Licitaciones por código CPV",
    description: "Concursos públicos de tecnología agrupados por código CPV.",
    url: "/cpv",
  },
  twitter: {
    ...TWITTER_COMPARTIDO,
    title: "Licitaciones por código CPV",
    description: "Concursos públicos de tecnología agrupados por código CPV.",
  },
};

export const revalidate = 3600;

export default async function IndiceCpv() {
  const { cpv } = await obtenerHubs();

  // 404 solo cuando el backend afirma que no hay códigos con volumen. Un fallo
  // de la API ya no llega hasta aquí como lista vacía: `obtenerHubs` lanza, la
  // regeneración ISR falla y Next sigue sirviendo el índice anterior en vez de
  // reemplazarlo por un 404 que Google tardaría semanas en desandar.
  if (cpv.length === 0) notFound();

  const migas = [
    { nombre: "Inicio", ruta: "/" },
    { nombre: "CPV", ruta: "/cpv" },
  ];
  const entradas = cpv.map((hub) => ({ titulo: `CPV ${hub.codigo}`, ruta: rutaHubCpv(hub.codigo) }));

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: serializarJsonLd([migasJsonLd(migas), listaJsonLd("Licitaciones por código CPV", entradas)]),
        }}
      />

      <div className="mx-auto w-full max-w-6xl px-6 py-12">
        <p className="text-primary flex items-center gap-2 font-mono text-xs tracking-widest uppercase">
          <Hash className="h-4 w-4" aria-hidden="true" />
          Por código CPV
        </p>
        <h1 className="font-display mt-3 text-3xl font-bold tracking-[-0.025em] text-balance md:text-4xl">
          Licitaciones por código CPV
        </h1>
        <p className="text-muted-foreground mt-4 max-w-[62ch] text-base leading-relaxed">
          El CPV (Common Procurement Vocabulary) es la clasificación con la que la administración identifica el objeto
          de cada contrato. Estos son los códigos con actividad en el corpus, ordenados por volumen.
        </p>

        <ul className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {cpv.map((hub) => (
            <li key={hub.codigo}>
              <Link
                href={rutaHubCpv(hub.codigo)}
                className="group border-border/70 bg-card focus-visible:ring-ring hover:border-primary/40 flex items-center justify-between gap-3 rounded-xl border px-5 py-4 transition-[transform,border-color,box-shadow] duration-200 ease-out hover:shadow-md focus-visible:ring-2 focus-visible:outline-none active:scale-[0.99]"
              >
                <span className="min-w-0">
                  <span className="block truncate font-mono text-sm font-semibold">{hub.codigo}</span>
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
          ¿Prefieres buscar por territorio?{" "}
          <Link href="/licitaciones" className="text-foreground font-medium underline underline-offset-4">
            Índice por comunidad autónoma
          </Link>
          .
        </p>
      </div>
    </>
  );
}
