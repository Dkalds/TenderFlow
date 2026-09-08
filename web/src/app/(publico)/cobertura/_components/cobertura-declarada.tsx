import { formatDate, ZONA_ES } from "@/lib/utils";
import { obtenerCobertura, type EstadoCobertura } from "../_lib/cobertura-api";
import { ESTADOS, EXCLUSIONES, FUENTES, SIN_INVENTARIO } from "../_lib/copy";

/**
 * Las fuentes con su estado, y lo que queda fuera del producto con su fecha.
 *
 * Es la mitad de `/cobertura` que **no** se escribe a mano: todo lo que se
 * pinta aquí llega de `GET /api/v1/publico/cobertura`, que a su vez lo lee del
 * inventario de conectores. El componente no ordena, no agrupa, no cuenta y no
 * completa: renderiza el orden que le dan y la frase que le dan (ADR-014).
 *
 * Lo único que deriva del dato es qué estados aparecen en la leyenda, y solo
 * para no explicar un estado que hoy no usa ninguna fuente.
 *
 * No hay ni un total. Es la regla dura de `docs/regional-source-coverage.md`:
 * estos feeds cubren universos distintos y sumarlos produciría un número que se
 * lee como cuota de mercado sin serlo.
 */

const ORDEN_ESTADOS: readonly EstadoCobertura[] = ["activa", "opcional", "fuera_de_alcance"];

function Badge({ estado }: { estado: EstadoCobertura }) {
  return (
    <span className="border-border/70 bg-background text-muted-foreground rounded-full border px-2.5 py-0.5 font-mono text-xs font-medium">
      {ESTADOS[estado].etiqueta}
    </span>
  );
}

export async function CoberturaDeclarada() {
  const cobertura = await obtenerCobertura();

  // El build de CI compila sin `API_BASE_URL` a propósito. Antes que una tabla
  // de fuentes vacía —la mentira más cara posible justo en esta página— la
  // página declara el hueco y la primera revalidación con backend lo rellena.
  if (!cobertura) {
    return (
      <section className="border-border/60 bg-card/40 border-t">
        <div className="mx-auto w-full max-w-4xl px-6 py-12">
          <h2 className="font-display text-2xl font-semibold tracking-normal">{FUENTES.titulo}</h2>
          <p className="text-muted-foreground mt-3 max-w-[68ch] text-sm leading-relaxed">{SIN_INVENTARIO}</p>
        </div>
      </section>
    );
  }

  const estadosPresentes = ORDEN_ESTADOS.filter((estado) =>
    cobertura.fuentes.some((fuente) => fuente.estado === estado),
  );

  return (
    <>
      <section aria-labelledby="fuentes-declaradas" className="border-border/60 bg-card/40 border-t">
        <div className="mx-auto w-full max-w-4xl px-6 py-12">
          <h2 id="fuentes-declaradas" className="font-display text-2xl font-semibold tracking-normal">
            {FUENTES.titulo}
          </h2>
          <p className="text-muted-foreground mt-3 max-w-[68ch] text-sm leading-relaxed">
            {FUENTES.introduccion}
          </p>

          <ul className="mt-8">
            {cobertura.fuentes.map((fuente) => (
              <li key={fuente.source_id} className="border-border/60 border-t py-5 first:border-t-0 first:pt-0">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                  <h3 className="font-display text-base font-semibold tracking-normal">{fuente.nombre}</h3>
                  <Badge estado={fuente.estado} />
                </div>
                <p className="text-muted-foreground mt-2 max-w-[68ch] text-sm leading-relaxed">{fuente.alcance}</p>
                <p className="text-muted-foreground mt-2 text-xs">
                  <span className="sr-only">{FUENTES.identificador}: </span>
                  <code className="font-mono">{fuente.source_id}</code>
                  <span aria-hidden="true"> · </span>
                  {FUENTES.frescuraPrefijo} {fuente.max_lag_hours} {FUENTES.frescuraSufijo}
                </p>
              </li>
            ))}
          </ul>

          <dl className="border-border/60 mt-8 grid gap-2 border-t pt-6 text-xs sm:grid-cols-3">
            {estadosPresentes.map((estado) => (
              <div key={estado}>
                <dt className="font-mono font-medium">{ESTADOS[estado].etiqueta}</dt>
                <dd className="text-muted-foreground mt-1 leading-relaxed">{ESTADOS[estado].glosa}</dd>
              </div>
            ))}
          </dl>

          <p className="text-muted-foreground mt-6 max-w-[68ch] text-xs leading-relaxed">{FUENTES.sinCuota}</p>
        </div>
      </section>

      <section aria-labelledby="fuera-de-alcance" className="border-border/60 border-t">
        <div className="mx-auto w-full max-w-4xl px-6 py-12">
          <h2 id="fuera-de-alcance" className="font-display text-2xl font-semibold tracking-normal">
            {EXCLUSIONES.titulo}
          </h2>
          <p className="text-muted-foreground mt-3 max-w-[68ch] text-sm leading-relaxed">
            {EXCLUSIONES.introduccion}
          </p>
          {/* La vía de entrada la declara el backend junto a las exclusiones:
              es parte de la decisión, no del envoltorio de esta página. */}
          <p className="mt-3 max-w-[68ch] text-sm leading-relaxed font-medium">{cobertura.via_de_entrada}</p>

          <ul className="mt-8">
            {cobertura.fuera_de_alcance.map((excluido) => (
              <li key={excluido.ambito} className="border-border/60 border-t py-5 first:border-t-0 first:pt-0">
                <h3 className="font-display text-base font-semibold tracking-normal">{excluido.ambito}</h3>
                <p className="text-muted-foreground mt-2 max-w-[68ch] text-sm leading-relaxed">{excluido.motivo}</p>
                <p className="text-muted-foreground mt-2 text-xs">
                  {EXCLUSIONES.decision} {excluido.decision}
                  <span aria-hidden="true"> · </span>
                  {EXCLUSIONES.desde}{" "}
                  <time dateTime={excluido.desde} className="text-foreground font-medium">
                    {formatDate(excluido.desde, "es-ES", ZONA_ES)}
                  </time>
                </p>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </>
  );
}
