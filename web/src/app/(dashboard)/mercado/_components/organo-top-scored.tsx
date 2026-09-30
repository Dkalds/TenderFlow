"use client";

/**
 * Las licitaciones mejor puntuadas del órgano abierto, como tarjetas.
 *
 * El color del distintivo sale de la **banda que calculó el backend**, no de
 * cortes propios: este ranking usa ya el mismo motor que el Radar
 * (Caliente/Atractiva/Tibia/Descarte), y los umbrales 80/60 eran los del
 * scoring A/B/C/D que se retiró.
 */

import { ChipBanda, SectionTitle } from "@/components/console/panel";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { Pista } from "@/components/ui/pista";
import { formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/utils";

import type { TopScoredItem } from "../_hooks/use-organos-view";

export function OrganoTopScored({ items }: { items: TopScoredItem[] }) {
  const visibles = items.slice(0, 30);
  return (
    <section>
      <SectionTitle as="h3" hint={formatNumber(visibles.length)}>
        Mejor puntuadas
      </SectionTitle>
      <ul className="space-y-2">
        {visibles.map((s, i) => (
          <li key={i} className="space-y-1 rounded-md border border-border/60 p-3">
            <div className="flex items-start justify-between gap-2">
              {s.url ? (
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="line-clamp-2 text-tf-body font-medium leading-tight text-primary hover:underline"
                >
                  {s.titulo ?? s.id_externo}
                  <AvisoPestanaNueva />
                </a>
              ) : (
                <p className="line-clamp-2 text-tf-body font-medium leading-tight">{s.titulo ?? s.id_externo}</p>
              )}
              {/* La banda es la del motor del Radar, con su color de
                  siempre; el score va al lado en cifra. */}
              <span className="flex flex-none items-center gap-1.5">
                <ChipBanda banda={s.banda} />
                <span className="text-tf-meta font-semibold">{s.score}</span>
              </span>
            </div>
            <p className="flex flex-wrap gap-x-1.5 gap-y-0.5 text-tf-meta text-muted-foreground">
              {[
                s.importe != null ? (
                  <span key="importe" className="font-medium text-foreground">
                    {formatCurrency(s.importe)}
                  </span>
                ) : null,
                s.estado_desc || s.estado ? <span key="estado">{s.estado_desc ?? s.estado}</span> : null,
                s.tipo_proyecto ? <span key="tipo">{s.tipo_proyecto}</span> : null,
                s.ccaa ? <span key="ccaa">{s.ccaa}</span> : null,
                s.empresa ? <span key="empresa">Adjudicataria: {s.empresa}</span> : null,
                s.baja_pct != null ? <span key="baja">Baja {formatPercent(s.baja_pct)}</span> : null,
                s.fecha_adjudicacion ? (
                  <span key="fecha">Adjudicada el {formatDate(s.fecha_adjudicacion)}</span>
                ) : null,
                s.modulos_str ? (
                  <span key="modulos" className="text-foreground">
                    {s.modulos_str}
                  </span>
                ) : null,
              ]
                .filter(Boolean)
                .flatMap((pieza, idx) =>
                  idx === 0
                    ? [pieza]
                    : [
                        <span key={`sep-${idx}`} aria-hidden="true">
                          ·
                        </span>,
                        pieza,
                      ],
                )}
            </p>
            {(s.tipo_contrato_desc || s.cpv_desc) && (
              <p className="flex min-w-0 flex-wrap gap-x-1.5 gap-y-0.5 text-tf-meta text-muted-foreground">
                {s.tipo_contrato_desc && <span>{s.tipo_contrato_desc}</span>}
                {s.tipo_contrato_desc && s.cpv_desc && <span aria-hidden="true">·</span>}
                {s.cpv_desc && (
                  <Pista contenido={s.cpv_desc}>
                    <span className="min-w-0 max-w-full truncate">{s.cpv_desc}</span>
                  </Pista>
                )}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
