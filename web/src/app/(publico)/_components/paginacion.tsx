import Link from "next/link";
import { formatNumber } from "@/lib/utils";

/**
 * Paginación de los hubs.
 *
 * Existe por una razón de rastreo, no de comodidad: sin ella, un hub muestra
 * las primeras 50 licitaciones y las demás quedan **huérfanas** — presentes en
 * el sitemap, así que Google las encuentra, pero sin un solo enlace que les
 * transmita autoridad. Una URL rastreable a la que no apunta nada rara vez
 * rankea.
 *
 * Los enlaces son `<a>` reales con su `href`, no botones que empujan estado:
 * un rastreador sigue enlaces, no `onClick`.
 *
 * Se pintan todas las páginas cuando son pocas y una ventana alrededor de la
 * actual cuando son muchas. La primera y la última siempre están presentes:
 * son las que reciben más enlaces internos y las que cierran el recorrido.
 */

const VENTANA = 2;

function paginasVisibles(actual: number, ultima: number): (number | "…")[] {
  if (ultima <= 7) return Array.from({ length: ultima }, (_, i) => i + 1);

  const cercanas = new Set<number>([1, ultima, actual]);
  for (let delta = 1; delta <= VENTANA; delta++) {
    if (actual - delta >= 1) cercanas.add(actual - delta);
    if (actual + delta <= ultima) cercanas.add(actual + delta);
  }

  const ordenadas = [...cercanas].sort((a, b) => a - b);
  const salida: (number | "…")[] = [];
  let previa = 0;
  for (const pagina of ordenadas) {
    if (previa && pagina - previa > 1) salida.push("…");
    salida.push(pagina);
    previa = pagina;
  }
  return salida;
}

export function Paginacion({
  base,
  paginaActual,
  total,
  porPagina,
}: {
  /** Ruta del hub, sin query. */
  base: string;
  paginaActual: number;
  total: number;
  porPagina: number;
}) {
  const ultima = Math.ceil(total / porPagina);
  if (ultima <= 1) return null;

  // La página 1 se enlaza sin `?p=1`: la misma lista bajo dos URLs distintas es
  // contenido duplicado, y el canonical de la página apunta a la versión limpia.
  const href = (pagina: number) => (pagina === 1 ? base : `${base}?p=${pagina}`);

  return (
    <nav aria-label="Paginación" className="border-border/50 mt-10 border-t pt-6">
      <p className="text-muted-foreground text-xs">
        Página {paginaActual} de {ultima} · {formatNumber(total)} licitaciones
      </p>
      <ul className="mt-3 flex flex-wrap items-center gap-1.5">
        {paginaActual > 1 && (
          <li>
            <Link
              href={href(paginaActual - 1)}
              rel="prev"
              className="border-input hover:bg-accent hover:text-accent-foreground inline-flex h-9 items-center rounded-md border px-3 text-sm font-medium"
            >
              Anterior
            </Link>
          </li>
        )}

        {paginasVisibles(paginaActual, ultima).map((pagina, indice) =>
          pagina === "…" ? (
            <li key={`hueco-${indice}`} className="text-muted-foreground px-1.5 text-sm">
              …
            </li>
          ) : (
            <li key={pagina}>
              <Link
                href={href(pagina)}
                aria-current={pagina === paginaActual ? "page" : undefined}
                className={
                  pagina === paginaActual
                    ? "bg-primary text-primary-foreground inline-flex h-9 min-w-9 items-center justify-center rounded-md px-3 text-sm font-semibold"
                    : "border-input hover:bg-accent hover:text-accent-foreground inline-flex h-9 min-w-9 items-center justify-center rounded-md border px-3 text-sm"
                }
              >
                {pagina}
              </Link>
            </li>
          ),
        )}

        {paginaActual < ultima && (
          <li>
            <Link
              href={href(paginaActual + 1)}
              rel="next"
              className="border-input hover:bg-accent hover:text-accent-foreground inline-flex h-9 items-center rounded-md border px-3 text-sm font-medium"
            >
              Siguiente
            </Link>
          </li>
        )}
      </ul>
    </nav>
  );
}
