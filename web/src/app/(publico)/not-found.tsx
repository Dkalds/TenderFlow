import type { Metadata } from "next";
import Link from "next/link";

/**
 * 404 de la superficie pública.
 *
 * Sin este fichero, un `notFound()` de un hub o de una ficha subía hasta
 * `app/not-found.tsx` —el límite más cercano era el raíz— y ese ofrecía «Ir al
 * resumen», que para un visitante anónimo es el dashboard: o sea un 307 a
 * `/login`. El recorrido acababa así: llegas desde Google a una licitación que
 * ya no está publicada, y el sitio te pide credenciales. Aquí el 404 se queda
 * dentro del layout público —con su cabecera, su pie y el CTA— y ofrece los dos
 * sitios desde los que se puede seguir buscando.
 *
 * `noindex` con `follow`: no es contenido que deba indexarse, pero sus enlaces
 * sí deben repartir autoridad hacia los hubs.
 */
export const metadata: Metadata = {
  title: "Página no encontrada",
  robots: { index: false, follow: true },
};

const DESTINOS = [
  { href: "/licitaciones", texto: "Licitaciones por comunidad autónoma" },
  { href: "/cpv", texto: "Licitaciones por código CPV" },
  { href: "/", texto: "Portada" },
];

export default function PublicoNotFound() {
  return (
    <section className="mx-auto w-full max-w-2xl px-6 py-24">
      <p className="text-muted-foreground font-mono text-xs tracking-widest uppercase">Error 404</p>
      <h1 className="font-display mt-3 text-3xl font-semibold tracking-[-0.02em] text-balance md:text-4xl">
        Esta página no existe
      </h1>
      <p className="text-muted-foreground mt-4 max-w-[58ch] text-base leading-relaxed">
        Puede que el anuncio ya no esté publicado, o que la dirección esté mal escrita. El corpus
        público se puede recorrer entero desde cualquiera de estos dos índices.
      </p>
      <ul className="mt-8 space-y-2">
        {DESTINOS.map((destino) => (
          <li key={destino.href}>
            <Link
              href={destino.href}
              className="text-primary focus-visible:ring-ring inline-flex rounded-sm text-base font-medium underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:outline-none"
            >
              {destino.texto}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
