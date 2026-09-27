import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { obtenerHubs } from "@/lib/publico-api";
import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { listaJsonLd, migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaHubCpv } from "@/lib/slug";
import { cn, formatNumber } from "@/lib/utils";
import { KICKER, TARJETA_INDICE, TITULO_PAGINA } from "../_components/piel-publica";

/**
 * Índice por código CPV.
 *
 * El CPV es el vocabulario común de contratación pública de la UE y buena parte
 * del público objetivo busca literalmente por código. Igual que
 * `/licitaciones`, este índice existe tanto para que la URL padre no devuelva
 * 404 como para que los hubs por código reciban enlaces internos.
 *
 * Los totales por código vienen del endpoint de hubs (ADR-014: aquí no se
 * agrega nada); las tarjetas comparten lenguaje visual con la landing.
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
        <p className={KICKER}>Por código CPV</p>
        <h1 className={cn(TITULO_PAGINA, "mt-3")}>Licitaciones por código CPV</h1>
        <p className="text-muted-foreground mt-4 max-w-[62ch] text-base leading-relaxed">
          El CPV (Common Procurement Vocabulary) es la clasificación con la que la administración identifica el objeto
          de cada contrato. Estos son los códigos con actividad en TenderFlow, ordenados por volumen.
        </p>

        <ul className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {cpv.map((hub) => (
            <li key={hub.codigo}>
              <Link href={rutaHubCpv(hub.codigo)} className={TARJETA_INDICE}>
                <span className="block min-w-0">
                  <span className="group-hover:text-primary block truncate font-mono text-sm font-semibold transition-colors">
                    {hub.codigo}
                  </span>
                  <span className="text-muted-foreground tf-tnum text-tf-meta mt-0.5 block">
                    {formatNumber(hub.total)} licitaciones
                  </span>
                </span>
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
