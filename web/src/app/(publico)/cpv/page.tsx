import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { obtenerHubs } from "@/lib/publico-api";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { listaJsonLd, migasJsonLd } from "@/lib/jsonld";
import { rutaHubCpv } from "@/lib/slug";
import { formatNumber } from "@/lib/utils";

/**
 * Índice por código CPV.
 *
 * El CPV es el vocabulario común de contratación pública de la UE y buena parte
 * del público objetivo busca literalmente por código. Igual que
 * `/licitaciones`, este índice existe tanto para que la URL padre no devuelva
 * 404 como para que los hubs por código reciban enlaces internos.
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
          __html: JSON.stringify([migasJsonLd(migas), listaJsonLd("Licitaciones por código CPV", entradas)]),
        }}
      />

      <div className="mx-auto w-full max-w-5xl px-6 py-12">
        <h1 className="font-display text-3xl font-bold tracking-[-0.025em] text-balance md:text-4xl">
          Licitaciones por código CPV
        </h1>
        <p className="text-muted-foreground mt-4 max-w-[62ch] text-base leading-relaxed">
          El CPV (Common Procurement Vocabulary) es la clasificación con la que la administración identifica el objeto
          de cada contrato. Estos son los códigos con actividad en el corpus, ordenados por volumen.
        </p>

        <ul className="mt-10 grid gap-x-8 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
          {cpv.map((hub) => (
            <li key={hub.codigo}>
              <Link
                href={rutaHubCpv(hub.codigo)}
                className="hover:bg-accent/60 flex items-baseline justify-between gap-3 rounded px-1 py-2"
              >
                <span className="font-mono text-sm font-medium">{hub.codigo}</span>
                <span className="text-muted-foreground text-xs tabular-nums">{formatNumber(hub.total)}</span>
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
