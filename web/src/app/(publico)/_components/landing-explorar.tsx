import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { CONTENIDO } from "../_content/landing";
import { FILA_EXPLORAR } from "./landing-piel";

/**
 * Explorar los datos.
 *
 * No es un bloque de navegación decorativo: es el único enlace desde la portada
 * —la página con más autoridad del sitio— hacia la superficie indexable. Sin
 * él, los hubs y las fichas quedan colgando solo del sitemap, que los hace
 * rastreables pero no les transmite relevancia.
 */
export function ExplorarLanding() {
  return (
    <div className="border-border/60 border-t">
      <section className="mx-auto w-full max-w-6xl px-6 py-16">
        <h2 className="font-display text-2xl font-semibold tracking-[-0.02em] md:text-3xl">
          {CONTENIDO.explorarTitulo}
        </h2>
        <p className="text-muted-foreground mt-3 max-w-[62ch] text-base leading-relaxed">{CONTENIDO.explorarTexto}</p>
        <div className="border-border/50 mt-8 border-t">
          {CONTENIDO.explorar.map((destino) => (
            <Link key={destino.href} href={destino.href} className={FILA_EXPLORAR}>
              <span className="min-w-0">
                <span className="font-display block text-lg font-semibold tracking-[-0.01em]">{destino.titulo}</span>
                <span className="text-muted-foreground mt-1 block text-sm leading-relaxed">{destino.texto}</span>
              </span>
              <ArrowUpRight
                className="text-muted-foreground group-hover:text-primary h-5 w-5 shrink-0 transition-[transform,color] duration-200 ease-out group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                aria-hidden="true"
              />
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
