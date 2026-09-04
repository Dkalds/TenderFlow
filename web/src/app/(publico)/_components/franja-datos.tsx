import { obtenerHubs, obtenerResumenPublico } from "@/lib/publico-api";
import { formatDate, formatNumber, ZONA_ES } from "@/lib/utils";
import { CONTENIDO } from "../_content/landing";

/**
 * Tres cifras reales del corpus y su fecha, bajo el hero.
 *
 * La landing no citaba ni un dato pese a tener tres agregados públicos a una
 * llamada de distancia. Una página cuyo producto vende confianza en el dato no
 * enseñaba ninguno, y el visitante tenía que creerse el tamaño del corpus.
 *
 * Cumple ADR-014 por construcción: los números salen tal cual del backend
 * —`/publico/sitemap/resumen` da el total y la fecha, `/publico/hubs` las dos
 * listas ya filtradas por su umbral—, y aquí sólo se cuenta la longitud de lo
 * que el endpoint devolvió. No se agrega, no se deriva y no se estima nada.
 *
 * Las etiquetas dicen exactamente lo que el número es. «Expedientes
 * publicables» y no «licitaciones en España»: el corpus público está filtrado
 * por umbral de sustancia y sin duplicados, así que llamarlo de otro modo sería
 * inflarlo. «Con hub» y «con volumen» por lo mismo — el backend sólo devuelve
 * las comunidades y los CPV que superan su mínimo de expedientes.
 *
 * La fecha responde a lo único que las tres cifras no acreditaban: **la
 * frescura**. El hero promete PLACSP cada cuatro horas y hasta ahora nada en
 * pantalla lo respaldaba, que es una promesa sin prueba en la página de un
 * producto que vende precisamente eso. Va como fecha absoluta y no como «hace
 * N horas» porque la página es ISR con una hora de revalidación: un relativo
 * calculado al generar puede llevar hasta una hora de retraso y se leería como
 * un dato en vivo que no es. La fecha absoluta no envejece mal, y `ZONA_ES` la
 * fija en la zona del corpus en vez de en el UTC del runtime.
 *
 * Sin animación de entrada de los números: el presupuesto de movimiento del
 * proyecto prohíbe animar el dato que el usuario vino a leer.
 */
export async function FranjaDatos() {
  const [resumen, hubs] = await Promise.all([obtenerResumenPublico(), obtenerHubs()]);

  // Qué queda en este camino, ahora que `publico-api` **lanza**.
  //
  // Desde 2026-08 un fallo de transporte o un 5xx ya no llegan aquí como un
  // objeto vacío: `obtenerResumenPublico`/`obtenerHubs` tiran `ErrorApiPublica`
  // y nadie la captura aguas arriba, a propósito (ver el docstring de
  // `lib/publico-api.ts`). Envolver este `Promise.all` en un `try/catch` para
  // servir la landing sin franja sería la degradación cómoda y el bug caro:
  // Next hornearía esa versión mutilada en la caché ISR durante la hora
  // siguiente, que es exactamente lo que ese módulo existe para no hacer. Con el
  // `throw`, la regeneración falla, **se conserva la copia buena** y se vuelve a
  // intentar; la landing sólo cae de verdad si la API está caída en el primer
  // render, cuando todavía no hay copia que conservar.
  //
  // Lo que sí se decide aquí es el otro caso, el que no es un error: la API
  // respondió y no hay corpus que citar. Pasa en el build de CI (compila sin
  // `API_BASE_URL`, y `pedir` degrada a "sin dato" sólo ahí) y pasaría con un
  // corpus vacío de verdad. Antes de enseñar ceros o un esqueleto, no se enseña
  // nada; con ISR, la primera revalidación con datos rellena la franja. El aviso
  // por consola existe porque desaparecer en silencio era el problema: la única
  // prueba dura de la página se esfumaba hasta una hora sin dejar rastro.
  if (resumen.total <= 0 || hubs.ccaa.length === 0 || hubs.cpv.length === 0) {
    console.warn(
      "[landing] franja de cifras omitida: la API pública no devolvió corpus",
      { total: resumen.total, ccaa: hubs.ccaa.length, cpv: hubs.cpv.length },
    );
    return null;
  }

  // `agruparSiempre`: las tres cifras se leen juntas, y sin él el recuento de
  // códigos CPV salía como "1038" al lado de "417.182" — mismo locale, dos
  // formatos, porque `es-ES` no agrupa los números de cuatro dígitos.
  const cifras = [
    { valor: formatNumber(resumen.total, "es-ES", { agruparSiempre: true }), etiqueta: CONTENIDO.franjaExpedientes },
    {
      valor: formatNumber(hubs.ccaa.length, "es-ES", { agruparSiempre: true }),
      etiqueta: CONTENIDO.franjaComunidades,
    },
    { valor: formatNumber(hubs.cpv.length, "es-ES", { agruparSiempre: true }), etiqueta: CONTENIDO.franjaCpv },
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
        {/* Un corpus sin fecha no pinta fecha. El backend la declara opcional
            justamente para que el consumidor pueda callarse en vez de inventar
            la prueba de frescura que el dato existe para respaldar. */}
        {resumen.actualizado && (
          <p className="text-muted-foreground mt-6 text-sm">
            {CONTENIDO.franjaActualizado}:{" "}
            <time dateTime={resumen.actualizado} className="text-foreground font-medium">
              {formatDate(resumen.actualizado, "es-ES", ZONA_ES)}
            </time>
          </p>
        )}
        <p className="text-muted-foreground mt-3 text-xs leading-relaxed">{CONTENIDO.franjaNota}</p>
      </div>
    </section>
  );
}
