import { contarPublicables, obtenerHubs } from "@/lib/publico-api";
import { formatNumber } from "@/lib/utils";
import { CONTENIDO } from "../_content/landing";

/**
 * Tres cifras reales del corpus, bajo el hero.
 *
 * La landing no citaba ni un dato pese a tener tres agregados públicos a una
 * llamada de distancia. Una página cuyo producto vende confianza en el dato no
 * enseñaba ninguno, y el visitante tenía que creerse el tamaño del corpus.
 *
 * Cumple ADR-014 por construcción: los tres números salen tal cual del backend
 * —`/publico/sitemap/resumen` da el total y `/publico/hubs` las dos listas ya
 * filtradas por su umbral—, y aquí sólo se cuenta la longitud de lo que el
 * endpoint devolvió. No se agrega, no se deriva y no se estima nada.
 *
 * Las etiquetas dicen exactamente lo que el número es. «Expedientes
 * publicables» y no «licitaciones en España»: el corpus público está filtrado
 * por umbral de sustancia y sin duplicados, así que llamarlo de otro modo sería
 * inflarlo. «Con hub» y «con volumen» por lo mismo — el backend sólo devuelve
 * las comunidades y los CPV que superan su mínimo de expedientes.
 *
 * Sin animación de entrada de los números: el presupuesto de movimiento del
 * proyecto prohíbe animar el dato que el usuario vino a leer.
 */
export async function FranjaDatos() {
  const [total, hubs] = await Promise.all([contarPublicables(), obtenerHubs()]);

  // La API puede no estar disponible en el build (CI construye sin backend) o
  // devolver un corpus vacío. Antes de enseñar ceros o un esqueleto, no se
  // enseña nada: con ISR, la primera revalidación con datos rellena la franja.
  if (total <= 0 || hubs.ccaa.length === 0 || hubs.cpv.length === 0) return null;

  const cifras = [
    { valor: formatNumber(total), etiqueta: CONTENIDO.franjaExpedientes },
    { valor: formatNumber(hubs.ccaa.length), etiqueta: CONTENIDO.franjaComunidades },
    { valor: formatNumber(hubs.cpv.length), etiqueta: CONTENIDO.franjaCpv },
  ];

  return (
    <section aria-label="El corpus en cifras" className="border-border/60 bg-card/40 border-y">
      <div className="mx-auto w-full max-w-6xl px-6 py-8">
        <dl className="grid gap-6 sm:grid-cols-3">
          {cifras.map((cifra) => (
            <div key={cifra.etiqueta}>
              <dt className="text-muted-foreground text-sm leading-relaxed">{cifra.etiqueta}</dt>
              <dd className="font-display tf-tnum mt-1 text-3xl font-semibold tracking-[-0.02em]">{cifra.valor}</dd>
            </div>
          ))}
        </dl>
        <p className="text-muted-foreground mt-6 text-xs leading-relaxed">{CONTENIDO.franjaNota}</p>
      </div>
    </section>
  );
}
