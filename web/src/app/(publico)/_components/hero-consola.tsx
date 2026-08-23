/**
 * Ilustración de la consola de triaje (Radar) para el hero de la landing.
 *
 * Es maquetación decorativa, no producto: `aria-hidden` porque no aporta nada
 * a un lector de pantalla que el texto del hero no diga ya. Server Component
 * puro —la landing entera se sirve sin JavaScript de cliente— y por eso todo
 * el movimiento es CSS (`animate-in` + `tf-stagger` de globals.css).
 *
 * ADR-014 (el frontend no fabrica datos) es la razón de que las "filas" sean
 * barras abstractas sin texto ni cifras: lo único real aquí es la estructura
 * del producto —bandas de score con sus colores (`--score-*`), las seis
 * dimensiones del scoring, la cadencia de ingesta y el intervalo p10/p50/p90—,
 * todo rastreable a código. Ningún expediente, importe o score inventado.
 */

const BANDAS = [
  { nombre: "Caliente", color: "hot" },
  { nombre: "Atractiva", color: "warm" },
  { nombre: "Tibia", color: "cold" },
  { nombre: "Descarte", color: "skip" },
] as const;

const PUNTO_BANDA: Record<(typeof BANDAS)[number]["color"], string> = {
  hot: "bg-[hsl(var(--score-hot))]",
  warm: "bg-[hsl(var(--score-warm))]",
  cold: "bg-[hsl(var(--score-cold))]",
  skip: "bg-[hsl(var(--score-skip))]",
};

/** Bandeja ordenada por score: anchos decorativos descendentes que cuentan la
 * mecánica real (el ranking llega ordenado), sin afirmar ningún valor. */
const FILAS = [
  { banda: "hot", titulo: "w-[72%]", meta: "w-[38%]", score: "w-[86%]" },
  { banda: "hot", titulo: "w-[58%]", meta: "w-[30%]", score: "w-[74%]" },
  { banda: "warm", titulo: "w-[66%]", meta: "w-[34%]", score: "w-[55%]" },
  { banda: "cold", titulo: "w-[48%]", meta: "w-[26%]", score: "w-[38%]" },
  { banda: "skip", titulo: "w-[62%]", meta: "w-[32%]", score: "w-[20%]" },
] as const;

/** Las seis dimensiones reales del scoring (services/scoring): los anchos de
 * los pesos son ilustrativos — los pesos son configurables por usuario. */
const DIMENSIONES = [
  { nombre: "Importe", peso: "w-[82%]" },
  { nombre: "Plazo", peso: "w-[54%]" },
  { nombre: "Competencia", peso: "w-[68%]" },
  { nombre: "Margen", peso: "w-[46%]" },
  { nombre: "Afinidad", peso: "w-[74%]" },
  { nombre: "Señal técnica", peso: "w-[60%]" },
] as const;

export function HeroConsola() {
  return (
    <div aria-hidden="true" className="relative select-none">
      {/* Halo cálido tras la tarjeta: profundidad sin recurrir a una imagen. */}
      <div className="absolute -inset-8 -z-10 rounded-[2.5rem] bg-[radial-gradient(closest-side,hsl(var(--primary)/0.18),transparent_72%)]" />

      <div className="animate-in fade-in-0 slide-in-from-bottom-2 anim-duration-500 border-border/70 bg-card tf-card-shadow overflow-hidden rounded-xl border [animation-delay:180ms]">
        {/* Chrome de ventana */}
        <div className="border-border/60 flex items-center justify-between border-b px-4 py-2.5">
          <div className="flex items-center gap-1.5">
            <span className="bg-muted-foreground/25 h-2.5 w-2.5 rounded-full" />
            <span className="bg-muted-foreground/25 h-2.5 w-2.5 rounded-full" />
            <span className="bg-muted-foreground/25 h-2.5 w-2.5 rounded-full" />
          </div>
          <span className="text-muted-foreground font-mono text-[10px] tracking-wide">radar · triaje diario</span>
          <span className="text-muted-foreground flex items-center gap-1.5 text-[10px] font-medium">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[hsl(var(--success))] opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[hsl(var(--success))]" />
            </span>
            PLACSP · cada 4 h
          </span>
        </div>

        {/* Chips de banda de score */}
        <div className="border-border/60 flex flex-wrap items-center gap-1.5 border-b px-4 py-2.5">
          {BANDAS.map((banda) => (
            <span
              key={banda.nombre}
              className="border-border/70 bg-background/60 text-muted-foreground inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-medium"
            >
              <span className={`h-1.5 w-1.5 rounded-full ${PUNTO_BANDA[banda.color]}`} />
              {banda.nombre}
            </span>
          ))}
        </div>

        <div className="grid sm:grid-cols-[minmax(0,1fr)_minmax(0,11.5rem)]">
          {/* Bandeja ordenada por score */}
          <ul className="tf-stagger divide-border/50 divide-y px-1.5 py-1.5">
            {FILAS.map((fila, i) => (
              <li
                key={i}
                className={`animate-in fade-in-0 slide-in-from-left-2 anim-duration-300 flex items-center gap-3 rounded-md px-2.5 py-2.5 ${
                  i === 0 ? "bg-[hsl(var(--primary)/0.07)]" : ""
                }`}
              >
                <span className={`h-2 w-2 shrink-0 rounded-full ${PUNTO_BANDA[fila.banda]}`} />
                <span className="min-w-0 flex-1 space-y-1.5">
                  <span className={`bg-foreground/15 block h-2 rounded-full ${fila.titulo}`} />
                  <span className={`bg-muted-foreground/20 block h-1.5 rounded-full ${fila.meta}`} />
                </span>
                <span className="bg-muted-foreground/15 h-1.5 w-16 shrink-0 overflow-hidden rounded-full">
                  <span
                    className={`tf-fill-enter block h-full rounded-full ${PUNTO_BANDA[fila.banda]} ${fila.score}`}
                  />
                </span>
              </li>
            ))}
          </ul>

          {/* Perfil de scoring: seis dimensiones con pesos configurables */}
          <div className="border-border/60 hidden border-l px-4 py-3.5 sm:block">
            <p className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">Perfil de scoring</p>
            <ul className="mt-3 space-y-2.5">
              {DIMENSIONES.map((dimension) => (
                <li key={dimension.nombre}>
                  <span className="text-muted-foreground text-[10px] leading-none font-medium">{dimension.nombre}</span>
                  <span className="bg-muted-foreground/15 mt-1 block h-1 overflow-hidden rounded-full">
                    <span className={`tf-fill-enter bg-primary/70 block h-full rounded-full ${dimension.peso}`} />
                  </span>
                </li>
              ))}
            </ul>

            {/* Intervalo de baja previsto p10/p50/p90 (real: predicción + calibración) */}
            <p className="text-muted-foreground mt-4 font-mono text-[10px] tracking-wider uppercase">Baja prevista</p>
            <div className="mt-2.5 px-0.5">
              <div className="bg-muted-foreground/25 relative h-px w-full">
                <span className="bg-muted-foreground/50 absolute top-1/2 left-[12%] h-2 w-px -translate-y-1/2" />
                <span className="border-card bg-primary absolute top-1/2 left-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2" />
                <span className="bg-muted-foreground/50 absolute top-1/2 right-[12%] h-2 w-px -translate-y-1/2" />
              </div>
              <div className="text-muted-foreground mt-1.5 flex justify-between font-mono text-[9px]">
                <span>p10</span>
                <span>p50</span>
                <span>p90</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
