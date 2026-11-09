import type { LicitacionPublica } from "@/lib/publico-api";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { fuenteOrigen } from "@/lib/fuentes";
import { urlHttp } from "@/lib/url-http";
import { fechaOpcional } from "./ficha-formato";

/**
 * Atribución de la fuente.
 *
 * No es cortesía: la Ley 37/2007 condiciona la reutilización a citar la fuente
 * e indicar la fecha de la última actualización, así que este bloque es un
 * requisito legal de la página, no un pie de página opcional. La fecha se pinta
 * sólo si existe — una atribución con un guion donde va la actualización no
 * cumple el requisito, y fingirla sería peor.
 *
 * El segundo párrafo es el aviso que evita el error caro: lo que se lee aquí es
 * un anuncio reutilizado, y el documento con el que se presenta una oferta es
 * el del perfil del contratante.
 */
export function AtribucionFuente({ lic }: { lic: LicitacionPublica }) {
  const actualizado = fechaOpcional(lic.actualizado);
  // La URL del anuncio la escribe quien publica: sin http(s), no hay enlace.
  const anuncio = urlHttp(lic.url);
  // La fuente de verdad, no «PLACSP o TED»: un anuncio de PSCP, Euskadi o
  // Galicia citaba a PLACSP, y la cita es lo que exige la ley.
  const fuente = fuenteOrigen(lic.fuente)?.nombre ?? "la plataforma de contratación de origen";

  return (
    <aside className="border-divider bg-card mt-12 rounded-xl border p-5 text-sm">
      <p className="text-muted-foreground">
        Fuente: <span className="text-foreground font-medium">{fuente}</span>. Datos reutilizados al amparo
        de la Ley 37/2007. {actualizado && <>Última actualización: {actualizado}.</>}
      </p>
      <p className="text-muted-foreground mt-3">
        Para presentar oferta, el documento válido es el del perfil del contratante.{" "}
        {anuncio && (
          <a
            href={anuncio}
            rel="nofollow noopener"
            target="_blank"
            className="text-foreground font-medium underline underline-offset-4"
          >
            Ver el anuncio oficial
            <AvisoPestanaNueva />
          </a>
        )}
      </p>
    </aside>
  );
}
