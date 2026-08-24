import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { LicitacionPublica } from "@/lib/publico-api";
import { listaJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaLicitacion } from "@/lib/slug";
import { EMPTY, formatCurrency, formatDate } from "@/lib/utils";

/**
 * Listado de licitaciones para los hubs.
 *
 * Server Component sin estado de cliente: lo que un rastreador lee es el HTML
 * de la respuesta, así que cualquier filtro o paginación que exigiera
 * hidratación escondería el contenido justo de quien tiene que verlo.
 *
 * Emite además el `ItemList` de datos estructurados desde el **mismo** array
 * que pinta, para que no puedan divergir.
 *
 * La fila entera es el enlace (un rastreador y un dedo agradecen lo mismo:
 * un área de toque grande con un solo destino), y los metadatos del anuncio
 * van como chips en vez de un párrafo corrido — mismo lenguaje visual que la
 * landing. Los valores son los que da el endpoint, tal cual: aquí no se
 * calcula ni se colorea nada (ADR-014).
 */

function fechaCorta(valor: string | null | undefined): string | null {
  const formateada = formatDate(valor);
  return formateada === EMPTY ? null : formateada;
}

const CHIP = "inline-flex items-center rounded-full border border-border/60 bg-background/60 px-2.5 py-0.5 text-xs";

export function ListadoLicitaciones({
  licitaciones,
  jsonLdNombre,
}: {
  licitaciones: LicitacionPublica[];
  jsonLdNombre: string;
}) {
  const entradas = licitaciones.map((lic) => ({
    titulo: lic.titulo,
    ruta: rutaLicitacion({ ccaa: lic.ccaa, titulo: lic.titulo, ref: lic.ref }),
  }));

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: serializarJsonLd(listaJsonLd(jsonLdNombre, entradas)) }}
      />

      <ul className="divide-border/50 border-border/50 mt-10 divide-y border-t">
        {licitaciones.map((lic, indice) => {
          const limite = fechaCorta(lic.fecha_limite);
          return (
            <li key={lic.ref}>
              <Link
                href={entradas[indice].ruta}
                className="group focus-visible:ring-ring hover:bg-accent/40 -mx-3 flex items-start justify-between gap-4 rounded-lg px-3 py-4 transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none sm:py-5"
              >
                <span className="min-w-0">
                  <h2 className="text-base leading-snug font-semibold underline-offset-4 group-hover:underline">
                    {lic.titulo}
                  </h2>
                  {lic.organo_contratacion && (
                    <p className="text-muted-foreground mt-1 text-sm">{lic.organo_contratacion}</p>
                  )}
                  <p className="mt-2.5 flex flex-wrap gap-1.5">
                    {lic.importe != null && (
                      <span className={`${CHIP} tf-tnum font-medium`}>{formatCurrency(lic.importe)}</span>
                    )}
                    {lic.cpv && <span className={`${CHIP} text-muted-foreground font-mono`}>CPV {lic.cpv}</span>}
                    {lic.provincia && <span className={`${CHIP} text-muted-foreground`}>{lic.provincia}</span>}
                    {limite && <span className={`${CHIP} text-muted-foreground`}>Hasta el {limite}</span>}
                    {lic.estado && <span className={`${CHIP} text-muted-foreground`}>{lic.estado}</span>}
                  </p>
                </span>
                <ArrowUpRight
                  aria-hidden="true"
                  className="text-muted-foreground group-hover:text-primary mt-1 hidden h-4 w-4 shrink-0 transition-[transform,color] duration-200 ease-out group-hover:translate-x-0.5 group-hover:-translate-y-0.5 sm:block"
                />
              </Link>
            </li>
          );
        })}
      </ul>
    </>
  );
}
