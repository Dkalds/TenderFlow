/**
 * Barras de carga de las dos listas del Radar.
 *
 * Existe porque el mismo bloque estaba copiado en `radar-lista.tsx` y en
 * `radar-proximas.tsx`, con la única diferencia del número de barras. Cada copia
 * llevaba su propio atributo de estilo en línea, y ese atributo es lo que
 * mantiene `style-src` atado a `'unsafe-inline'` (C2.8): un desvanecido
 * duplicado costaba dos, y aquí cuesta uno.
 *
 * La opacidad se calcula por índice —la lista se difumina hacia abajo, para que
 * el esqueleto sugiera continuidad en vez de un bloque plano— y por eso no puede
 * ser una clase de Tailwind: el valor depende de la posición.
 */
export function RadarEsqueleto({ barras }: { barras: number }) {
  return (
    <div className="flex flex-col gap-2.5 p-3.5">
      {Array.from({ length: barras }, (_, index) => (
        <span
          key={index}
          className="tf-shimmer block h-11 rounded-lg"
          style={{ opacity: 1 - index * 0.07 }}
        />
      ))}
    </div>
  );
}
