/**
 * F4.1 — la previsión por trimestre y los supuestos del valor ponderado.
 *
 * Las dos piezas que Oportunidades → Rendimiento y Dirección enseñan igual:
 * el reparto por trimestre de adjudicación prevista y las probabilidades por
 * etapa con las que se ponderó. Las cifras vienen hechas (`prevision_trimestral`,
 * `probabilidades_etapa_usadas`); aquí sólo se ordenan y se dibujan barras
 * proporcionales al trimestre mayor.
 */
import { SectionTitle } from "@/components/console/panel";
import type { SupuestoEtapa, TrimestrePrevision } from "@/lib/pipeline-ponderado";
import { cn, formatCompactCurrency } from "@/lib/utils";

export function SupuestosEtapas({
  supuestos,
  className,
}: {
  supuestos: SupuestoEtapa[];
  className?: string;
}) {
  if (supuestos.length === 0) return null;
  return (
    <dl
      className={cn("flex flex-wrap gap-x-4 gap-y-1 text-tf-micro", className)}
      aria-label="Probabilidad por etapa"
    >
      {supuestos.map((s) => (
        <div key={s.etapa} className="flex gap-1">
          <dt className="text-muted-foreground">{s.etiqueta}</dt>
          <dd className="tf-tnum font-medium">{s.probabilidad} %</dd>
        </div>
      ))}
    </dl>
  );
}

/** `2026-Q4` del instante dado, para comparar con las claves de la previsión. */
export function trimestreDe(ahora: Date): string {
  return `${ahora.getFullYear()}-Q${Math.floor(ahora.getMonth() / 3) + 1}`;
}

export function PrevisionTrimestral({
  prevision,
  titulo = "Previsión por trimestre",
  ahora = new Date(),
}: {
  prevision: TrimestrePrevision[];
  titulo?: string;
  /** Para decir qué trimestres ya pasaron; inyectable en los tests. */
  ahora?: Date;
}) {
  const maxTrimestre = Math.max(1, ...prevision.map((t) => t.valor));
  // Una adjudicación prevista en un trimestre que ya pasó no es «lo que viene»:
  // es una oportunidad abierta que va con retraso, y se dice. Comparar claves
  // `AAAA-QN` es comparar texto, no calcular nada.
  const actual = trimestreDe(ahora);
  return (
    <>
      <SectionTitle className="mt-4 mb-2">{titulo}</SectionTitle>
      {prevision.length === 0 ? (
        <p className="text-tf-meta text-muted-foreground">
          Sin oportunidades abiertas con importe y fecha para repartir.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {prevision.map((t) => (
            <li key={t.clave} className="grid grid-cols-[64px_1fr_72px] items-center gap-3">
              <span className="text-tf-meta text-muted-foreground">
                {t.etiqueta}
                {t.clave < actual ? <span className="block text-tf-micro text-warning">con retraso</span> : null}
              </span>
              <div className="h-4 overflow-hidden rounded-sm bg-secondary/60" aria-hidden="true">
                {/* Barra en SVG: el ancho es un atributo, no un estilo inline (C2.8). */}
                <svg className="h-full w-full" preserveAspectRatio="none" viewBox="0 0 100 1">
                  <rect
                    className="fill-primary/60"
                    height="1"
                    width={Math.max(2, (t.valor / maxTrimestre) * 100)}
                  />
                </svg>
              </div>
              <span className="tf-tnum text-right text-tf-meta font-semibold">
                {formatCompactCurrency(t.valor)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-tf-micro text-muted-foreground">
        El trimestre sale de la fecha prevista de adjudicación y, sin ella, de la fecha límite.
        {prevision.some((t) => t.clave < actual)
          ? " «Con retraso»: la fecha prevista ya pasó y la oportunidad sigue abierta."
          : null}
      </p>
    </>
  );
}
