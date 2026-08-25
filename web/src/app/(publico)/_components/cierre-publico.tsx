import { solicitarAccesoHref } from "@/lib/contacto";
import { CONTENIDO } from "../_content/landing";
import { EnlaceSolicitarAcceso } from "./enlace-solicitar-acceso";

/**
 * Cierre de los hubs públicos.
 *
 * Los hubs son las páginas por las que de verdad se entra desde un buscador —la
 * portada la ve quien ya conoce la marca— y no tenían ninguna salida hacia el
 * producto: alguien llegaba desde Google, leía cincuenta anuncios y se iba. La
 * cabecera ya ofrece solicitar acceso desde que se corrigió el layout, pero un
 * botón de chrome no cierra nada; hace falta decir qué hay dentro que no esté
 * en la lista que se acaba de leer.
 *
 * Va en los hubs (`[ccaa]`, `[codigo]`) y **no** en los dos índices: esos son
 * navegación —listas de enlaces a los hubs— y quien los cruza está buscando
 * dónde entrar, no decidiendo nada.
 *
 * Las tres cosas que promete son las mismas que la landing, y existen: score de
 * oportunidad, baja de referencia por segmento y módulo competitivo.
 */
export function CierrePublico({ ubicacion }: { ubicacion: string }) {
  return (
    <aside className="border-border/60 bg-card/40 mt-14 rounded-xl border p-6 sm:flex sm:items-center sm:justify-between sm:gap-8">
      <div className="max-w-[52ch]">
        <p className="font-display text-lg font-semibold tracking-[-0.01em]">{CONTENIDO.publicoCierreTitulo}</p>
        <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">{CONTENIDO.publicoCierreTexto}</p>
      </div>
      <EnlaceSolicitarAcceso
        href={solicitarAccesoHref(ubicacion)}
        ubicacion={ubicacion}
        className="bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:ring-ring focus-visible:ring-offset-background mt-5 inline-flex h-11 shrink-0 items-center justify-center rounded-md px-6 text-sm font-semibold shadow-md transition-[transform,background-color] duration-150 ease-out focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none active:scale-[0.97] sm:mt-0"
      >
        {CONTENIDO.ctaPrimario}
      </EnlaceSolicitarAcceso>
    </aside>
  );
}
