import type { LicitacionPublica } from "@/lib/publico-api";
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

  return (
    <aside className="border-border/60 bg-card/40 mt-12 rounded-xl border p-5 text-sm">
      <p className="text-muted-foreground">
        Datos procedentes de la{" "}
        <span className="text-foreground font-medium">
          {lic.fuente === "ted"
            ? "base de datos TED de la Unión Europea"
            : "Plataforma de Contratación del Sector Público"}
        </span>
        , reutilizados al amparo de la Ley 37/2007. {actualizado && <>Última actualización: {actualizado}.</>}
      </p>
      <p className="text-muted-foreground mt-3">
        Para presentar oferta, el documento válido es el del perfil del contratante.{" "}
        {lic.url && (
          <a
            href={lic.url}
            rel="nofollow noopener"
            target="_blank"
            className="text-foreground font-medium underline underline-offset-4"
          >
            Ver el anuncio oficial
          </a>
        )}
      </p>
    </aside>
  );
}
