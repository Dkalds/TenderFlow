import type { LicitacionPublica } from "@/lib/publico-api";
import { estadoLabel } from "@/lib/estados";
import { listaJsonLd, serializarJsonLd } from "@/lib/jsonld";
import { rutaLicitacion } from "@/lib/slug";
import { cn, formatCurrency } from "@/lib/utils";
import { EnlacePrecargaIntencion } from "./enlace-precarga-intencion";
import { plazoPresentacion } from "./plazo";

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
 * un área de toque grande con un solo destino), y por eso no lleva flecha: el
 * subrayado del título al pasar el ratón ya dice que se abre. Los metadatos del
 * anuncio van como chips en vez de un párrafo corrido. El enlace se precarga
 * solo ante una intención de abrirlo
 * (`EnlacePrecargaIntencion`): las fichas son ISR y precargar las cincuenta de
 * la página al pintarla costaría cincuenta renders en frío. Los valores son los que da el endpoint, tal cual: aquí no se
 * calcula ni se colorea nada (ADR-014).
 *
 * Lo único que se traduce es la **presentación**, que no es derivar dato: el
 * código de estado se pasa por `estadoLabel` —la API devuelve `AGR`/`EJEC` en
 * crudo y ninguna respuesta los traduce— y la fecha límite por
 * `plazoPresentacion`, que dice si el plazo sigue abierto. Ambos son mapeos
 * deterministas del valor que dio el backend, sin agregarlo ni completarlo.
 */

/* Chip de metadato: `rounded-md` como todo chip de la casa, sin fondo. */
const CHIP = "inline-flex items-center rounded-md border border-border/60 px-2 py-0.5 text-tf-meta";

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

  // Un solo instante para toda la lista: si cada fila leyera su reloj, dos
  // anuncios que cierran el mismo día podrían caer a distinto lado de la
  // medianoche dentro del mismo HTML.
  const ahora = new Date();

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: serializarJsonLd(listaJsonLd(jsonLdNombre, entradas)) }}
      />

      <ul className="divide-border/50 border-border/50 mt-10 divide-y border-t">
        {licitaciones.map((lic, indice) => {
          const plazo = plazoPresentacion(lic.fecha_limite, ahora);
          return (
            <li key={lic.ref}>
              <EnlacePrecargaIntencion
                href={entradas[indice].ruta}
                className="group focus-visible:ring-ring hover:bg-primary/5 -mx-3 block rounded-md px-3 py-4 transition-colors focus-visible:ring-2 focus-visible:outline-none sm:py-5"
              >
                <h2 className="text-base leading-snug font-semibold underline-offset-4 group-hover:underline">
                  {lic.titulo}
                </h2>
                {lic.organo_contratacion && (
                  <p className="text-muted-foreground mt-1 text-sm">{lic.organo_contratacion}</p>
                )}
                <p className="mt-2.5 flex flex-wrap gap-1.5">
                  {lic.importe != null && (
                    <span className={cn(CHIP, "tf-tnum font-medium")}>{formatCurrency(lic.importe)}</span>
                  )}
                  {lic.cpv && (
                    <span className={cn(CHIP, "text-muted-foreground")}>
                      CPV&nbsp;<span className="font-mono">{lic.cpv}</span>
                    </span>
                  )}
                  {lic.provincia && <span className={cn(CHIP, "text-muted-foreground")}>{lic.provincia}</span>}
                  {plazo && (
                    <span className={cn(CHIP, "text-muted-foreground")}>
                      {plazo.vencido ? "Plazo cerrado el" : "Hasta el"} {plazo.fecha}
                    </span>
                  )}
                  {lic.estado && <span className={cn(CHIP, "text-muted-foreground")}>{estadoLabel(lic.estado)}</span>}
                </p>
              </EnlacePrecargaIntencion>
            </li>
          );
        })}
      </ul>
    </>
  );
}
