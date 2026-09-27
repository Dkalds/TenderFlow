import { solicitarAccesoHref } from "@/lib/contacto";
import { cn } from "@/lib/utils";
import { CONTENIDO } from "../_content/landing";
import { EnlaceSolicitarAcceso } from "./enlace-solicitar-acceso";
import { CTA_PRIMARIO } from "./piel-publica";

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
 * Va en los hubs (`[ccaa]`, `[codigo]`) y en la ficha, que es el otro final de
 * recorrido orgánico: quien la lee entera ya sabe si el contrato le interesa, y
 * hasta 2026-08 lo único que se le ofrecía ahí era /login, donde el alta está
 * apagada. **No** va en los dos índices: esos son navegación —listas de enlaces
 * a los hubs— y quien los cruza está buscando dónde entrar, no decidiendo nada.
 *
 * Las tres cosas que promete son las mismas que la landing, y existen: score de
 * oportunidad, baja de referencia por segmento y módulo competitivo.
 */
export function CierrePublico({ ubicacion }: { ubicacion: string }) {
  return (
    <aside className="border-border/60 bg-card mt-14 rounded-xl border p-6 sm:flex sm:items-center sm:justify-between sm:gap-8">
      <div className="max-w-[52ch]">
        <p className="font-display text-lg font-semibold tracking-[-0.01em]">{CONTENIDO.publicoCierreTitulo}</p>
        <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">{CONTENIDO.publicoCierreTexto}</p>
      </div>
      <EnlaceSolicitarAcceso
        href={solicitarAccesoHref()}
        ubicacion={ubicacion}
        className={cn(CTA_PRIMARIO, "mt-5 shrink-0 sm:mt-0")}
      >
        {CONTENIDO.ctaPrimario}
      </EnlaceSolicitarAcceso>
    </aside>
  );
}
