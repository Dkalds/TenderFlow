import Link from "next/link";
import type { LicitacionPublica } from "@/lib/publico-api";
import { listaJsonLd } from "@/lib/jsonld";
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
 */

function fechaCorta(valor: string | null | undefined): string | null {
  const formateada = formatDate(valor);
  return formateada === EMPTY ? null : formateada;
}

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
        dangerouslySetInnerHTML={{ __html: JSON.stringify(listaJsonLd(jsonLdNombre, entradas)) }}
      />

      <ul className="divide-border/50 border-border/50 mt-10 divide-y border-t">
        {licitaciones.map((lic, indice) => {
          const limite = fechaCorta(lic.fecha_limite);
          return (
            <li key={lic.ref} className="py-5">
              <h2 className="text-base leading-snug font-semibold">
                <Link href={entradas[indice].ruta} className="underline-offset-4 hover:underline">
                  {lic.titulo}
                </Link>
              </h2>
              {lic.organo_contratacion && (
                <p className="text-muted-foreground mt-1 text-sm">{lic.organo_contratacion}</p>
              )}
              <p className="text-muted-foreground mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                {lic.importe && <span>{formatCurrency(lic.importe)}</span>}
                {lic.cpv && <span className="font-mono">CPV {lic.cpv}</span>}
                {lic.provincia && <span>{lic.provincia}</span>}
                {limite && <span>Hasta el {limite}</span>}
                {lic.estado && <span>{lic.estado}</span>}
              </p>
            </li>
          );
        })}
      </ul>
    </>
  );
}
