import Link from "next/link";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { ANCLA_SOLICITUD } from "@/lib/contacto";
import { cn } from "@/lib/utils";
import { CONTENIDO } from "../_content/landing";
import { CTA_PRIMARIO, KICKER } from "./piel-publica";

export interface SeccionEvidencia {
  titulo: string;
  texto: string[];
  puntos?: string[];
}

/**
 * Plantilla de las tres páginas de evidencia: /cobertura, /metodologia y
 * /seguridad.
 *
 * Sin los numerales 01/02/03 al margen ni un check naranja por viñeta
 * (auditoría F46): son justo lo que la portada retiró como esqueleto de
 * plantilla, y aquí seguían. Las secciones se separan por filete y los puntos
 * van en una lista con filete a la izquierda; el rótulo es el `KICKER` de toda
 * la superficie pública.
 */
export function PaginaEvidencia({
  kicker,
  titulo,
  introduccion,
  secciones,
}: {
  kicker: string;
  titulo: string;
  introduccion: string;
  secciones: SeccionEvidencia[];
}) {
  return (
    <article className="mx-auto w-full max-w-4xl px-6 py-12 md:py-16">
      <Link
        href="/"
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex items-center gap-2 rounded-sm text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Volver a TenderFlow
      </Link>

      <header className="mt-10 max-w-3xl">
        <p className={KICKER}>{kicker}</p>
        <h1 className="font-display mt-3 text-4xl leading-tight font-semibold tracking-[-0.02em] text-balance md:text-5xl">
          {titulo}
        </h1>
        <p className="text-muted-foreground mt-5 text-lg leading-relaxed text-pretty">{introduccion}</p>
      </header>

      <div className="mt-12">
        {secciones.map((seccion) => (
          <section key={seccion.titulo} className="border-border/60 border-t py-9">
            <div className="max-w-[68ch]">
              <h2 className="font-display text-2xl font-semibold tracking-[-0.02em] text-balance">{seccion.titulo}</h2>
              {seccion.texto.map((parrafo) => (
                <p key={parrafo} className="text-muted-foreground mt-4 text-base leading-relaxed">
                  {parrafo}
                </p>
              ))}
              {seccion.puntos ? (
                <ul className="border-border/60 mt-6 space-y-3 border-l pl-4">
                  {seccion.puntos.map((punto) => (
                    <li key={punto} className="text-sm leading-relaxed md:text-base">
                      {punto}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </section>
        ))}
      </div>

      <footer className="border-border/60 mt-4 border-t pt-10">
        <p className="font-display max-w-[34ch] text-2xl font-semibold tracking-[-0.02em] text-balance">
          Contrasta estas reglas con tus propios expedientes.
        </p>
        {/* Misma etiqueta que los otros cuatro CTA del sitio. Decía «Solicitar
            revisión», que nombraba una acción distinta de la que ocurre y
            rompía el recuento del test que exige que todos los botones de
            acceso lleven al mismo formulario. */}
        <Link href={`/#${ANCLA_SOLICITUD}`} className={cn(CTA_PRIMARIO, "mt-6 px-5")}>
          {CONTENIDO.ctaPrimario}
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </footer>
    </article>
  );
}
