import Link from "next/link";
import { listarLicitaciones } from "@/lib/publico-api";
import { estadoLabel } from "@/lib/estados";
import { rutaLicitacion } from "@/lib/slug";
import { formatCurrency, formatDate, ZONA_ES } from "@/lib/utils";
import { CONTENIDO } from "../_content/landing";
import { plazoPresentacion } from "./plazo";

/**
 * Los últimos anuncios publicados, en el hero.
 *
 * La portada enseñaba una captura de pantalla del producto: una imagen de un
 * expediente inventado, con su nota de «datos de demostración». Es el gesto por
 * defecto de una landing de software y en este producto concreto era el peor
 * disponible — TenderFlow no vende una interfaz, vende que el dato está ahí y
 * está fresco, y para eso una foto vale menos que el dato mismo. Aquí hay cinco
 * expedientes reales, cada uno con su enlace a la ficha pública, servidos por la
 * misma API que alimenta el resto del sitio.
 *
 * Cumple ADR-014 por construcción: se pinta lo que devuelve
 * `GET /publico/licitaciones` y no se agrega, ordena ni completa nada. El orden
 * lo pone el backend (`ORDER BY fecha_publicacion DESC`, ver
 * `db/repositories/publico.py`), y por eso el rótulo dice «publicados» y no
 * «incorporados»: son cosas distintas y el endpoint no ofrece la segunda.
 * Llamarlo de otro modo sería inflar lo que el dato acredita.
 *
 * Async Server Component, como `FranjaDatos`: la página sigue siendo estática
 * con ISR, así que la llamada ocurre al generar y no en cada visita.
 *
 * Qué pasa cuando la API no contesta: nada especial, y es deliberado.
 * `listarLicitaciones` lanza ante un fallo de transporte o un 5xx y nadie lo
 * captura, así que la regeneración falla y Next conserva la copia buena. Un
 * `try/catch` aquí hornearía en la caché ISR una portada sin su prueba durante
 * la hora siguiente. Lo que sí se decide es el otro caso —la API respondió y no
 * hay nada— y ahí no se enseña un hueco: se devuelve `null`, igual que la franja.
 */
export async function UltimosPublicados() {
  const { items } = await listarLicitaciones({ limit: 5 });

  if (items.length === 0) {
    console.warn("[landing] últimos publicados omitidos: la API pública no devolvió anuncios");
    return null;
  }

  // Un solo instante para toda la lista: si cada fila leyera su reloj, dos
  // anuncios que cierran el mismo día podrían caer a distinto lado de la
  // medianoche dentro del mismo HTML.
  const ahora = new Date();
  const masReciente = items[0].fecha_publicacion;

  return (
    <section aria-labelledby="ultimos-titulo" className="border-border/60 border-t pt-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 id="ultimos-titulo" className="text-sm font-semibold">
          {CONTENIDO.ultimosTitulo}
        </h2>
        {masReciente && (
          <p className="text-muted-foreground text-xs">
            {CONTENIDO.ultimosFecha}{" "}
            <time dateTime={masReciente} className="text-foreground font-medium">
              {formatDate(masReciente, "es-ES", ZONA_ES)}
            </time>
          </p>
        )}
      </div>

      <ul className="divide-border/40 mt-2 divide-y">
        {items.map((lic) => {
          const plazo = plazoPresentacion(lic.fecha_limite, ahora);
          return (
            <li key={lic.ref}>
              <Link
                href={rutaLicitacion({ ccaa: lic.ccaa, titulo: lic.titulo, ref: lic.ref })}
                className="group focus-visible:ring-ring -mx-2 block rounded-md px-2 py-3 transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none"
              >
                <span className="block text-sm leading-snug font-medium underline-offset-4 group-hover:underline">
                  {lic.titulo}
                </span>
                <span className="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs">
                  {lic.organo_contratacion && <span className="truncate">{lic.organo_contratacion}</span>}
                  {lic.importe != null && (
                    <span className="tf-tnum text-foreground/80 font-medium">{formatCurrency(lic.importe)}</span>
                  )}
                  {lic.ccaa && <span>{lic.ccaa}</span>}
                  {plazo && <span>{plazo.vencido ? `Cerrado el ${plazo.fecha}` : `Hasta el ${plazo.fecha}`}</span>}
                  {lic.estado && <span>{estadoLabel(lic.estado)}</span>}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>

      <Link
        href="/licitaciones"
        className="text-primary focus-visible:ring-ring mt-3 inline-flex rounded-sm text-sm font-medium underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:outline-none"
      >
        {CONTENIDO.ultimosEnlace}
      </Link>
    </section>
  );
}
