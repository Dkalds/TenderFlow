import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { obtenerLicitacion, type LicitacionPublica } from "@/lib/publico-api";
import { SITE_NAME, TWITTER_COMPARTIDO } from "@/lib/site";
import { migasJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaHubCcaa, rutaLicitacion } from "@/lib/slug";
import { EMPTY, formatCurrency, formatDate } from "@/lib/utils";

/**
 * Ficha pública de una licitación.
 *
 * Solo el anuncio oficial: nada de scoring, predicción de baja, escenarios de
 * precio ni adjudicatario. La proyección la impone el backend
 * (`db/repositories/publico.py`) y `scripts/check_public_surface.py` la
 * verifica en CI, pero conviene saberlo también al editar esta página.
 *
 * La ruta lleva cuatro segmentos —`/licitaciones/{ccaa}/{slug}/{ref}`— y la
 * referencia va suelta en el último. Ver `lib/slug.ts`: el alfabeto base64url
 * incluye `-`, así que pegarla al slug haría imposible saber dónde acaba uno.
 *
 * Presentación: los tres datos que deciden si el anuncio interesa
 * (presupuesto, fecha límite, publicación) van como destacados; el resto en la
 * tabla de datos. Todo son valores del endpoint tal cual — aquí no se calcula
 * ni se interpreta nada (ADR-014).
 */

type Params = { ccaa: string; slug: string; ref: string };

function fecha(valor: string | null | undefined): string | null {
  const formateada = formatDate(valor);
  return formateada === EMPTY ? null : formateada;
}

function nombreFuente(lic: LicitacionPublica): string {
  return lic.fuente === "ted" ? "TED · Unión Europea" : "PLACSP";
}

function descripcionSeo(lic: LicitacionPublica): string {
  const partes = [
    lic.organo_contratacion,
    lic.importe ? `Presupuesto ${formatCurrency(lic.importe)}` : null,
    lic.ccaa,
    lic.cpv ? `CPV ${lic.cpv}` : null,
  ].filter(Boolean);
  return `${partes.join(" · ")}. Anuncio oficial, plazos y lotes.`.slice(0, 160);
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { ref } = await params;
  const lic = await obtenerLicitacion(ref);
  if (!lic) return { title: "Licitación no encontrada", robots: { index: false } };

  // El canonical se calcula desde el dato **actual**, no desde la URL que se
  // pidió. Si el órgano corrige el título, el slug cambia pero la referencia
  // no: la URL antigua sigue resolviendo y se declara a sí misma como copia de
  // la nueva, en vez de competir con ella en el índice.
  const canonical = rutaLicitacion({ ccaa: lic.ccaa, titulo: lic.titulo, ref: lic.ref });
  const descripcion = descripcionSeo(lic);

  // Aquí NO se esparce `OG_IMAGE_COMPARTIDA`: este segmento tiene su propia
  // `opengraph-image.tsx` con los datos del anuncio, y los metadatos por
  // convención de fichero tienen prioridad. Declarar además la genérica
  // emitiría dos `og:image` compitiendo.
  return {
    title: lic.titulo.slice(0, 70),
    description: descripcion,
    alternates: { canonical },
    openGraph: {
      title: lic.titulo.slice(0, 70),
      description: descripcion,
      url: canonical,
      type: "article",
    },
    twitter: { ...TWITTER_COMPARTIDO, title: lic.titulo.slice(0, 70), description: descripcion },
  };
}

export default async function FichaLicitacion({ params }: { params: Promise<Params> }) {
  const { ref } = await params;
  const lic = await obtenerLicitacion(ref);
  if (!lic) notFound();

  // `lotes` es opcional en el esquema generado: Pydantic lo declara con
  // `default_factory`, así que no sale como requerido en el OpenAPI.
  const lotes = lic.lotes ?? [];

  const migas = [
    { nombre: "Inicio", ruta: "/" },
    { nombre: lic.ccaa ?? "Sin comunidad", ruta: rutaHubCcaa(lic.ccaa) },
    {
      nombre: lic.titulo,
      ruta: rutaLicitacion({ ccaa: lic.ccaa, titulo: lic.titulo, ref: lic.ref }),
    },
  ];

  // Los tres datos de decisión, como destacados; solo se pintan los presentes.
  const destacados: [string, string | null][] = [
    ["Presupuesto", lic.importe ? formatCurrency(lic.importe) : null],
    ["Fecha límite", fecha(lic.fecha_limite)],
    ["Publicación", fecha(lic.fecha_publicacion)],
  ];

  // El resto del anuncio. Lo que ya está arriba (destacados y chips de
  // cabecera: estado y expediente) no se repite aquí.
  const datos: [string, string | null][] = [
    ["Órgano de contratación", lic.organo_contratacion ?? null],
    ["CPV", lic.cpv ?? null],
    ["Tipo de contrato", lic.tipo_contrato ?? null],
    ["Procedimiento", lic.procedimiento ?? null],
    ["Tramitación", lic.tramitacion ?? null],
    ["Inicio de ejecución", fecha(lic.fecha_inicio)],
    ["Fin de ejecución", fecha(lic.fecha_fin)],
    ["Duración", lic.duracion_valor ? `${lic.duracion_valor} ${lic.duracion_unidad ?? ""}`.trim() : null],
    ["Provincia", lic.provincia ?? null],
    ["Comunidad autónoma", lic.ccaa ?? null],
  ];

  const CHIP =
    "inline-flex items-center rounded-full border border-border/60 bg-card/60 px-2.5 py-0.5 text-xs font-medium";

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializarJsonLd(migasJsonLd(migas)) }} />

      <article className="mx-auto w-full max-w-4xl px-6 py-12">
        <nav aria-label="Migas de pan" className="text-muted-foreground mb-6 text-xs">
          <ol className="flex flex-wrap items-center gap-1.5">
            {migas.slice(0, -1).map((miga) => (
              <li key={miga.ruta} className="flex items-center gap-1.5">
                <Link href={miga.ruta} className="hover:text-foreground transition-colors duration-150">
                  {miga.nombre}
                </Link>
                <span aria-hidden="true">/</span>
              </li>
            ))}
            <li className="text-foreground/70 truncate">{lic.titulo.slice(0, 60)}</li>
          </ol>
        </nav>

        {/* Cabecera del anuncio: fuente, estado y expediente, tal como los da
            el endpoint. */}
        <p className="flex flex-wrap items-center gap-1.5">
          <span className={`${CHIP} border-primary/30 bg-primary/[0.06] text-primary font-mono`}>
            {nombreFuente(lic)}
          </span>
          {lic.estado && <span className={`${CHIP} text-muted-foreground`}>{lic.estado}</span>}
          {lic.expediente && <span className={`${CHIP} text-muted-foreground font-mono`}>Exp. {lic.expediente}</span>}
        </p>

        <h1 className="font-display mt-4 text-3xl leading-[1.15] font-bold tracking-[-0.025em] text-balance md:text-4xl">
          {lic.titulo}
        </h1>

        {lic.descripcion && (
          <p className="text-muted-foreground mt-6 max-w-[68ch] text-base leading-relaxed whitespace-pre-line">
            {lic.descripcion}
          </p>
        )}

        {destacados.some(([, valor]) => valor) && (
          <dl className="mt-8 grid gap-3 sm:grid-cols-3">
            {destacados
              .filter((par): par is [string, string] => Boolean(par[1]))
              .map(([etiqueta, valor]) => (
                <div key={etiqueta} className="border-border/70 bg-card rounded-xl border p-4">
                  <dt className="text-muted-foreground text-[11px] tracking-wide uppercase">{etiqueta}</dt>
                  <dd className="font-display tf-tnum mt-1 text-xl font-semibold tracking-[-0.01em]">{valor}</dd>
                </div>
              ))}
          </dl>
        )}

        <h2 className="font-display mt-12 text-xl font-semibold tracking-[-0.02em]">Datos del anuncio</h2>
        <dl className="border-border/70 bg-card mt-5 grid gap-x-10 gap-y-4 rounded-xl border p-6 sm:grid-cols-2">
          {datos
            .filter((par): par is [string, string] => Boolean(par[1]))
            .map(([etiqueta, valor]) => (
              <div key={etiqueta}>
                <dt className="text-muted-foreground text-[11px] tracking-wide uppercase">{etiqueta}</dt>
                <dd className="mt-0.5 text-sm font-medium">{valor}</dd>
              </div>
            ))}
        </dl>

        {lotes.length > 0 && (
          <>
            <h2 className="font-display mt-12 text-xl font-semibold tracking-[-0.02em]">Lotes ({lotes.length})</h2>
            <div className="border-border/70 bg-card mt-5 overflow-x-auto rounded-xl border px-5 py-2">
              <table className="w-full min-w-[32rem] text-sm">
                <thead>
                  <tr className="border-border/60 text-muted-foreground border-b text-left text-[11px] tracking-wide uppercase">
                    <th className="py-2.5 pr-4 font-medium">Nº</th>
                    <th className="py-2.5 pr-4 font-medium">Objeto</th>
                    <th className="py-2.5 pr-4 font-medium">CPV</th>
                    <th className="py-2.5 font-medium">Importe</th>
                  </tr>
                </thead>
                <tbody>
                  {lotes.map((lote) => (
                    <tr key={lote.numero} className="border-border/30 border-b last:border-b-0">
                      <td className="py-2.5 pr-4 font-mono text-xs">{lote.numero}</td>
                      <td className="py-2.5 pr-4">{lote.titulo ?? "—"}</td>
                      <td className="py-2.5 pr-4 font-mono text-xs">{lote.cpv ?? "—"}</td>
                      <td className="tf-tnum py-2.5">{formatCurrency(lote.importe)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* Atribución. No es cortesía: la Ley 37/2007 condiciona la
            reutilización a citar la fuente e indicar la fecha de la última
            actualización, así que este bloque es un requisito legal de la
            página, no un pie de página opcional. */}
        <aside className="border-border/60 bg-card/40 mt-12 rounded-xl border p-5 text-sm">
          <p className="text-muted-foreground">
            Datos procedentes de la{" "}
            <span className="text-foreground font-medium">
              {lic.fuente === "ted"
                ? "base de datos TED de la Unión Europea"
                : "Plataforma de Contratación del Sector Público"}
            </span>
            , reutilizados al amparo de la Ley 37/2007.{" "}
            {fecha(lic.actualizado) && <>Última actualización: {fecha(lic.actualizado)}.</>}
          </p>
          <p className="text-muted-foreground mt-3">
            Para presentar oferta, el documento válido es el del perfil del contratante.{" "}
            {lic.url && (
              <a
                href={lic.url}
                rel="nofollow noopener"
                target="_blank"
                className="text-foreground font-medium underline underline-offset-4"
              >
                Ver el anuncio oficial
              </a>
            )}
          </p>
        </aside>

        <div className="mt-10 flex flex-wrap gap-3">
          <Link
            href={rutaHubCcaa(lic.ccaa)}
            className="border-input hover:bg-accent hover:text-accent-foreground inline-flex h-10 items-center rounded-md border px-5 text-sm font-medium transition-[transform,background-color,border-color] duration-150 ease-out active:scale-[0.97]"
          >
            Más licitaciones {lic.ccaa ? `en ${lic.ccaa}` : ""}
          </Link>
          {/* utm_content=ficha: en Vercel Analytics se ve cuántos llegan a
              /login desde una ficha indexada — el camino orgánico completo. */}
          <Link
            href="/login?utm_source=publico&utm_content=ficha"
            className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex h-10 items-center rounded-md px-5 text-sm font-semibold shadow-md transition-[transform,background-color] duration-150 ease-out active:scale-[0.97]"
          >
            Seguir este contrato con {SITE_NAME}
          </Link>
        </div>
      </article>
    </>
  );
}

// Los `ccaa` y `slug` de la URL son decorativos: la referencia identifica el
// expediente por sí sola. Se aceptan tal cual en vez de validarlos contra el
// dato para no convertir un enlace con el slug antiguo en un 404 — el
// `canonical` de `generateMetadata` ya le dice a Google cuál es la buena.
export const dynamicParams = true;
export const revalidate = 3600;
