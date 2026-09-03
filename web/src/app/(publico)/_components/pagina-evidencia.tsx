import Link from "next/link";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { ANCLA_SOLICITUD } from "@/lib/contacto";
import { CONTENIDO } from "../_content/landing";

export interface SeccionEvidencia {
  titulo: string;
  texto: string[];
  puntos?: string[];
}

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
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex items-center gap-2 rounded-sm text-sm font-medium transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Volver a TenderFlow
      </Link>

      <header className="mt-10 max-w-3xl">
        <p className="text-primary font-mono text-xs font-semibold tracking-widest uppercase">{kicker}</p>
        <h1 className="font-display mt-3 text-4xl leading-tight font-bold tracking-[-0.02em] text-balance md:text-5xl">
          {titulo}
        </h1>
        <p className="text-muted-foreground mt-5 text-lg leading-relaxed text-pretty">{introduccion}</p>
      </header>

      <div className="mt-12">
        {secciones.map((seccion, indice) => (
          <section
            key={seccion.titulo}
            className="border-border/60 grid gap-5 border-t py-9 md:grid-cols-[3rem_minmax(0,1fr)] md:gap-7"
          >
            <span className="text-muted-foreground font-mono text-xs" aria-hidden="true">
              {String(indice + 1).padStart(2, "0")}
            </span>
            <div className="max-w-[68ch]">
              <h2 className="font-display text-2xl font-semibold tracking-[-0.02em] text-balance">{seccion.titulo}</h2>
              {seccion.texto.map((parrafo) => (
                <p key={parrafo} className="text-muted-foreground mt-4 text-base leading-relaxed">
                  {parrafo}
                </p>
              ))}
              {seccion.puntos ? (
                <ul className="mt-6 space-y-3">
                  {seccion.puntos.map((punto) => (
                    <li key={punto} className="flex gap-3 text-sm leading-relaxed md:text-base">
                      <Check className="text-primary mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                      <span>{punto}</span>
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
          Contrasta estas reglas con vuestros propios expedientes.
        </p>
        {/* Misma etiqueta que los otros cuatro CTA del sitio. Decía «Solicitar
            revisión», que nombraba una acción distinta de la que ocurre y
            rompía el recuento del test que exige que todos los botones de
            acceso lleven al mismo formulario. */}
        <Link
          href={`/#${ANCLA_SOLICITUD}`}
          className="bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:ring-ring focus-visible:ring-offset-background mt-6 inline-flex h-11 items-center justify-center gap-2 rounded-md px-5 text-sm font-semibold shadow-md transition-[transform,background-color] duration-150 ease-out focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none active:scale-[0.97]"
        >
          {CONTENIDO.ctaPrimario}
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </footer>
    </article>
  );
}
