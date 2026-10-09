/**
 * F4.2 — las cuatro cifras de arriba: lo ganado, el éxito, lo que viene y el
 * tiempo, cada una con su periodo anterior.
 *
 * **Presenta, no calcula** (ADR-014, invariante 1 de `web/AGENTS.md`): el
 * valor, el anterior, la diferencia, la `n`, el mínimo y el universo vienen
 * del backend. Por debajo del mínimo llega `valor: null` con una nota «Sin
 * base: …», y aquí se enseña esa nota en el sitio de la cifra — nunca un cero
 * ni un «—» mudo.
 *
 * La `n` va siempre a la vista; el universo, plegado en «Cómo se calcula».
 * Cuatro tarjetas con tres líneas de metodología cada una tapaban la cifra, y
 * un `<details>` y no un `title`: el tooltip nativo no existe para teclado ni
 * táctil.
 */
import { ROTULO_DATO } from "@/components/console/panel";
import { cn, formatNumber } from "@/lib/utils";
import { formatoCifra, lineaComparacion, tonoDelta, type Tarjeta } from "../_lib/formato";

const TONO_DELTA = {
  mejor: "text-success",
  peor: "text-destructive",
  igual: "text-muted-foreground",
} as const;

function TarjetaCifra({ tarjeta }: { tarjeta: Tarjeta }) {
  const cifra = tarjeta.valor != null ? formatoCifra(tarjeta.unidad, tarjeta.valor) : null;
  const comparacion = lineaComparacion(tarjeta);
  const tono = tonoDelta(tarjeta);
  return (
    <li className="flex min-w-0 flex-col gap-1 bg-card px-3.5 py-3">
      <h3 className={ROTULO_DATO}>{tarjeta.etiqueta}</h3>
      {cifra != null ? (
        <p className="tf-tnum text-tf-title font-semibold">{cifra}</p>
      ) : (
        <p className="text-tf-body font-medium">Sin base</p>
      )}
      {comparacion ? (
        <p className={cn("tf-tnum text-tf-meta", tono ? TONO_DELTA[tono] : "text-muted-foreground")}>
          {comparacion}
        </p>
      ) : null}
      {tarjeta.nota ? <p className="text-tf-meta text-muted-foreground">{tarjeta.nota}</p> : null}
      <div className="mt-auto pt-1 text-tf-micro text-muted-foreground">
        <span className="tf-tnum">
          n = {formatNumber(tarjeta.n ?? 0)}
          {(tarjeta.n_minimo ?? 1) > 1 ? ` (mínimo ${tarjeta.n_minimo})` : ""}
        </span>
        <details className="mt-1">
          <summary className="cursor-pointer select-none hover:text-foreground">Cómo se calcula</summary>
          <p className="mt-1 leading-relaxed">{tarjeta.universo}</p>
        </details>
      </div>
    </li>
  );
}

export function TarjetasDireccion({ tarjetas }: { tarjetas: Tarjeta[] }) {
  if (tarjetas.length === 0) return null;
  return (
    <section aria-labelledby="direccion-resumen" className="flex flex-col gap-2">
      <h2 id="direccion-resumen" className="sr-only">
        Cifras del periodo
      </h2>
      <ul
        className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-border/60 bg-border/60 sm:grid-cols-2 xl:grid-cols-4"
        aria-label="Cifras de dirección"
      >
        {tarjetas.map((tarjeta) => (
          <TarjetaCifra key={tarjeta.clave} tarjeta={tarjeta} />
        ))}
      </ul>
    </section>
  );
}
