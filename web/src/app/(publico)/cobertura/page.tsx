import type { Metadata } from "next";
import Link from "next/link";
import { PaginaEvidencia } from "../_components/pagina-evidencia";
import { CONTENIDO } from "../_content/landing";
import { CoberturaDeclarada } from "./_components/cobertura-declarada";
import { CABECERA, META, SECCIONES } from "./_lib/copy";

/**
 * `/cobertura` — qué entra en el producto, con qué alcance, y qué queda fuera.
 *
 * La página tenía tres bloques de prosa que nombraban PLACSP, TED, Galicia y
 * Euskadi a mano cuando el repositorio ya registraba siete fuentes. Nada
 * fallaba: una declaración de cobertura escrita a mano no se entera de que el
 * código cambió. Desde T7 (D16, 2026-09-06) el inventario y las exclusiones
 * salen de `GET /api/v1/publico/cobertura`; lo que queda aquí escrito son las
 * reglas de entrada, que no viven en ninguna tabla.
 */

export const metadata: Metadata = {
  title: META.title,
  description: META.description,
  alternates: { canonical: "/cobertura" },
};

/**
 * Una hora, como el resto de la superficie pública. La cobertura declarada
 * cambia con un despliegue, no con una ingesta, así que revalidar más a menudo
 * solo gastaría regeneraciones.
 */
export const revalidate = 3600;

export default function CoberturaPage() {
  return (
    <>
      <PaginaEvidencia
        kicker={CABECERA.kicker}
        titulo={CABECERA.titulo}
        introduccion={CABECERA.introduccion}
        secciones={SECCIONES}
      />
      <CoberturaDeclarada />
      <section className="border-border/60 bg-card/40 border-t">
        <div className="mx-auto w-full max-w-4xl px-6 py-12">
          <h2 className="font-display text-2xl font-semibold tracking-normal">Familias observadas</h2>
          <p className="text-muted-foreground mt-3 max-w-[68ch] text-sm leading-relaxed">
            {CONTENIDO.familiasTitulo}
          </p>
          <ul className="mt-6 flex flex-wrap gap-2">
            {CONTENIDO.familias.map((familia) => (
              <li key={familia} className="border-border/70 bg-background rounded-md border px-3 py-1.5 text-sm font-medium">
                {familia}
              </li>
            ))}
          </ul>
          <div className="mt-8 flex flex-wrap gap-x-5 gap-y-3 text-sm font-medium">
            <Link href="/licitaciones" className="text-primary underline-offset-4 hover:underline">
              Explorar por comunidad autónoma
            </Link>
            <Link href="/cpv" className="text-primary underline-offset-4 hover:underline">
              Explorar por código CPV
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
