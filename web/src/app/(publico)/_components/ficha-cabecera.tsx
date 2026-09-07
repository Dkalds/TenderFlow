import Link from "next/link";
import type { LicitacionPublica } from "@/lib/publico-api";
import { estadoLabel } from "@/lib/estados";

/** Una miga de pan: el mismo par que alimenta el JSON-LD de la ficha. */
export interface Miga {
  nombre: string;
  ruta: string;
}

const CHIP =
  "inline-flex items-center rounded-full border border-border/60 bg-card/60 px-2.5 py-0.5 text-xs font-medium";

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
 * `RES`) y publicar el código es publicar jerga interna del emisor.
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
              <span aria-hidden="true">/</span>
            </li>
          ))}
          <li className="text-foreground/70 truncate">{lic.titulo.slice(0, 60)}</li>
        </ol>
      </nav>

      {/* Cabecera del anuncio: fuente, estado y expediente, tal como los da
          el endpoint. */}
      <p className="flex flex-wrap items-center gap-1.5">
        <span className={`${CHIP} border-primary/30 bg-primary/[0.06] text-primary font-mono`}>
          {nombreFuente(lic)}
        </span>
        {lic.estado && <span className={`${CHIP} text-muted-foreground`}>{estadoLabel(lic.estado)}</span>}
        {lic.expediente && <span className={`${CHIP} text-muted-foreground font-mono`}>Exp. {lic.expediente}</span>}
      </p>

      <h1 className="font-display mt-4 text-3xl leading-[1.15] font-bold tracking-[-0.025em] text-balance md:text-4xl">
        {lic.titulo}
      </h1>

      {lic.descripcion && (
        <p className="text-muted-foreground mt-6 max-w-[68ch] text-base leading-relaxed whitespace-pre-line">
          {lic.descripcion}
        </p>
      )}
    </>
  );
}
