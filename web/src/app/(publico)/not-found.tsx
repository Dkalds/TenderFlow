import type { Metadata } from "next";
import { cn } from "@/lib/utils";
import { EnlaceIrPublico } from "./_components/enlace-ir";
import { KICKER, TITULO_PAGINA } from "./_components/piel-publica";

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
      <p className={KICKER}>Error 404</p>
      <h1 className={cn(TITULO_PAGINA, "mt-3")}>Esta página no existe</h1>
      <p className="text-muted-foreground mt-4 max-w-[58ch] text-base leading-relaxed">
        Puede que el anuncio ya no esté publicado, o que la dirección esté mal escrita. Los anuncios públicos se pueden
        recorrer enteros desde los índices por comunidad autónoma y por código CPV.
      </p>
      <ul className="mt-8 space-y-3">
        {DESTINOS.map((destino) => (
          <li key={destino.href}>
            <EnlaceIrPublico href={destino.href} className="text-base">
              {destino.texto}
            </EnlaceIrPublico>
          </li>
        ))}
      </ul>
    </section>
  );
}
