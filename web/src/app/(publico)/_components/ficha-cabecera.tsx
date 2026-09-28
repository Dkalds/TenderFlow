import Link from "next/link";
import type { LicitacionPublica } from "@/lib/publico-api";
import { estadoLabel } from "@/lib/estados";
import { cn } from "@/lib/utils";
import { TITULO_PAGINA } from "./piel-publica";

/** Una miga de pan: el mismo par que alimenta el JSON-LD de la ficha. */
export interface Miga {
  nombre: string;
  ruta: string;
}

/* Chip de metadato: `rounded-md` como todo chip de la casa (la píldora es para
 * puntos y avatares), sin fondo translúcido. */
const CHIP = "inline-flex items-center rounded-md border border-border/60 px-2 py-0.5 text-tf-meta font-medium";

function nombreFuente(lic: LicitacionPublica): string {
  return lic.fuente === "ted" ? "TED · Unión Europea" : "PLACSP";
}

/**
 * Cabecera de la ficha pública: migas, procedencia, título y objeto.
 *
 * Las migas se reciben ya construidas porque la página las necesita también
 * para el `BreadcrumbList` del JSON-LD: construirlas aquí obligaría a tener dos
 * listas, y una miga que se pinta distinta de la que se marca es exactamente lo
 * que Google trata como marcado que no describe la página.
 *
 * De los tres chips, dos son valores crudos de la fuente y uno no: el estado
 * pasa por `estadoLabel` porque la API lo devuelve como código (`AGR`, `EJEC`,
 * `RES`) y publicar el código es publicar jerga interna del emisor. Solo el
 * expediente va en monoespaciada, porque es un identificador; el nombre de la
 * fuente es una palabra.
 */
export function CabeceraFicha({ lic, migas }: { lic: LicitacionPublica; migas: Miga[] }) {
  return (
    <>
      <nav aria-label="Migas de pan" className="text-muted-foreground mb-6 text-xs">
        <ol className="flex flex-wrap items-center gap-1.5">
          {migas.slice(0, -1).map((miga) => (
            <li key={miga.ruta} className="flex items-center gap-1.5">
              <Link href={miga.ruta} className="hover:text-foreground transition-colors duration-150">
                {miga.nombre}
              </Link>
              <span aria-hidden="true">›</span>
            </li>
          ))}
          <li className="text-foreground/70 truncate">{lic.titulo.slice(0, 60)}</li>
        </ol>
      </nav>

      {/* Cabecera del anuncio: fuente, estado y expediente, tal como los da
          el endpoint. */}
      <p className="flex flex-wrap items-center gap-1.5">
        <span className={cn(CHIP, "border-primary/30 bg-primary/10 text-primary")}>{nombreFuente(lic)}</span>
        {lic.estado && <span className={cn(CHIP, "text-muted-foreground")}>{estadoLabel(lic.estado)}</span>}
        {lic.expediente && (
          <span className={cn(CHIP, "text-muted-foreground")}>
            Exp.&nbsp;<span className="font-mono">{lic.expediente}</span>
          </span>
        )}
      </p>

      <h1 className={cn(TITULO_PAGINA, "mt-4")}>{lic.titulo}</h1>

      {lic.descripcion && (
        <p className="text-muted-foreground mt-6 max-w-[68ch] text-base leading-relaxed whitespace-pre-line">
          {lic.descripcion}
        </p>
      )}
    </>
  );
}
