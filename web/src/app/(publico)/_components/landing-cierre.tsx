import { LEGAL_RESPONSABLE } from "@/lib/legal";
import { CONTENIDO } from "../_content/landing";
import { FormularioSolicitud } from "./formulario-solicitud";

/**
 * Cierre de la portada, y el destino de los tres CTA.
 *
 * Sin el resplandor radial de fondo: el gradiente decorativo detrás del último
 * bloque es otro de los gestos por defecto, y aquí competía con el único
 * formulario de la página.
 */
export function CierreLanding() {
  return (
    <section className="border-border/60 border-t">
      <div className="mx-auto w-full max-w-6xl px-6 py-20">
        {/* `lg` y no `md`: a 768 px el contenedor deja 664 px para las dos
            pistas, la fija se lleva sus 32rem y a la columna de texto le
            quedaban 152 px — el titular se salía de su caja. A partir de
            1024 px hay sitio de sobra para las dos. */}
        <div className="grid gap-x-14 gap-y-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,28rem)]">
          <div>
            <h2 className="font-display max-w-[18ch] text-3xl font-semibold tracking-[-0.02em] text-balance md:text-4xl">
              {CONTENIDO.cierreTitulo}
            </h2>
            <p className="text-muted-foreground mt-5 max-w-[52ch] text-base leading-relaxed">{CONTENIDO.cierreTexto}</p>
            <p className="text-muted-foreground mt-5 text-xs">{CONTENIDO.cierreNota}</p>
            {/* Quién hay detrás, en la misma pantalla en la que se pide un
                correo. Sólo si el entorno publica una identidad real:
                `lib/legal.ts` devuelve `null` cuando falta o cuando lleva un
                valor de relleno. */}
            {LEGAL_RESPONSABLE && (
              <p className="text-muted-foreground mt-2 text-xs">
                {CONTENIDO.responsablePrefijo}{" "}
                <span className="text-foreground/80 font-medium">{LEGAL_RESPONSABLE}</span>
              </p>
            )}
          </div>
          {/* El destino del CTA, aquí mismo. Los tres botones saltan a este
              ancla en vez de abrir un cliente de correo. */}
          <FormularioSolicitud />
        </div>
      </div>
    </section>
  );
}
