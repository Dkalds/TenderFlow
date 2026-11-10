"use client";

/**
 * Las celdas que comparten el marco y el contrato basado de `ficha-marco.tsx`:
 * admitidos, pertenencia de tu organización y vigencia.
 */

import * as React from "react";
import Link from "next/link";
import { Fact } from "@/components/console/panel";
import { FechaFinOrigenBadge } from "@/components/pursuits/fecha-fin-origen-badge";
import type { MarcoDeLicitacion } from "@/lib/api-types";
import { formatDate, formatNumber } from "@/lib/utils";

export const REJILLA = "border-divider bg-divider grid gap-px overflow-hidden rounded-md border";
export const NOTA = "text-muted-foreground text-tf-meta block font-normal text-pretty";
export const DESPLEGABLE = "text-primary w-fit cursor-pointer rounded-sm font-medium hover:underline";

export function contar(n: number, singular: string, plural: string): string {
  return `${formatNumber(n)} ${n === 1 ? singular : plural}`;
}

function lotesDe(lotes: string[]): string | null {
  if (lotes.length === 0) return null;
  return lotes.length === 1 ? `Lote ${lotes[0]}` : `Lotes ${lotes.join(", ")}`;
}

/** Un valor que la fuente no da, con el motivo debajo. */
export function SinDato({ children }: { children: React.ReactNode }) {
  return (
    <>
      Sin dato
      <span className={NOTA}>{children}</span>
    </>
  );
}

export function Admitidos({ marco, label, esSda }: { marco: MarcoDeLicitacion; label: string; esSda: boolean }) {
  const total = marco.admitidos_total ?? 0;
  return (
    <Fact
      label={label}
      value={
        total > 0 ? (
          <span className="tf-tnum">{contar(total, "empresa", "empresas")}</span>
        ) : esSda ? (
          // Medido el 2026-11-10: PLACSP y TED no publican quién entra en un sistema dinámico.
          <SinDato>No hay empresas admitidas publicadas. En un sistema dinámico las fuentes casi nunca las publican.</SinDato>
        ) : (
          <SinDato>La fuente no ha publicado admitidos. Aparecen cuando se adjudica.</SinDato>
        )
      }
    />
  );
}

export function ListaDeAdmitidos({ marco }: { marco: MarcoDeLicitacion }) {
  const total = marco.admitidos_total ?? 0;
  const admitidos = marco.admitidos ?? [];
  if (total === 0) return null;
  return (
    <details className="text-tf-meta mt-3">
      <summary className={DESPLEGABLE}>
        Ver {total === 1 ? "la empresa admitida" : `las ${formatNumber(total)} empresas admitidas`}
      </summary>
      <ul className="divide-divider mt-1 divide-y">
        {admitidos.map((admitido) => (
          <li key={`${admitido.nif ?? ""}-${admitido.nombre}`} className="py-2">
            <p className="text-tf-body flex flex-wrap items-baseline gap-x-2 font-medium">
              <span>{admitido.nombre}</span>
              {admitido.nif && (
                <span className="text-muted-foreground text-tf-meta font-mono font-normal">{admitido.nif}</span>
              )}
            </p>
            <p className="text-muted-foreground">
              {[admitido.es_tu_organizacion ? "Tu organización" : null, lotesDe(admitido.lotes ?? [])]
                .filter(Boolean)
                .join(" · ") || "Sin lotes publicados"}
            </p>
          </li>
        ))}
      </ul>
      {total > admitidos.length ? (
        <p className="text-muted-foreground mt-1">
          Y {contar(total - admitidos.length, "empresa más", "empresas más")}, por orden alfabético.
        </p>
      ) : null}
    </details>
  );
}

export function TuOrganizacion({ marco }: { marco: MarcoDeLicitacion }) {
  const label = "Tu organización";
  if (!marco.identidad_conocida) {
    return (
      <Fact
        label={label}
        value={
          <>
            <Link href="/equipo?tab=organizacion" className="text-primary hover:underline">
              Declara el NIF de tu organización
            </Link>
            <span className={NOTA}>Sin él no se puede decir si estás entre los admitidos.</span>
          </>
        }
      />
    );
  }
  if (marco.organizacion_admitida === true) {
    const propia = (marco.admitidos ?? []).find((a) => a.es_tu_organizacion);
    const lotes = lotesDe(propia?.lotes ?? []);
    return (
      <Fact
        label={label}
        tono="success"
        value={
          <>
            Está admitida
            {lotes ? <span className={NOTA}>{lotes}</span> : null}
          </>
        }
      />
    );
  }
  if (marco.organizacion_admitida === false) {
    return <Fact label={label} value="No está entre los admitidos" />;
  }
  // Con NIF declarado y sin respuesta: o no hay admitidos, o alguno llegó sin NIF.
  if (!marco.admitidos_total) return null;
  return (
    <Fact
      label={label}
      value={<SinDato>Hay admitidos publicados sin NIF: no se puede descartar que seas uno de ellos.</SinDato>}
    />
  );
}

const UNIDAD_DURACION = { ANN: ["año", "años"], MON: ["mes", "meses"], DAY: ["día", "días"] } as const;

function duracionPublicada(vigencia: MarcoDeLicitacion["vigencia"]): string | null {
  if (vigencia?.duracion_valor == null || !vigencia.duracion_unidad) return null;
  const [singular, plural] = UNIDAD_DURACION[vigencia.duracion_unidad];
  return contar(vigencia.duracion_valor, singular, plural);
}

export function Vigencia({ vigencia, label }: { vigencia: MarcoDeLicitacion["vigencia"]; label: string }) {
  if (!vigencia?.fecha_fin) {
    const duracion = duracionPublicada(vigencia);
    return (
      <Fact
        label={label}
        value={
          duracion ? (
            // Hay duración pero no desde cuándo contarla: típico del marco que aún se licita.
            <>
              <span className="tf-tnum">{duracion}</span>
              <span className={NOTA}>Todavía sin fecha de fin: no se ha publicado el inicio ni la adjudicación.</span>
            </>
          ) : (
            <SinDato>La fuente no publica fecha de fin ni duración.</SinDato>
          )
        }
      />
    );
  }
  const dias = vigencia.dias_restantes;
  return (
    <Fact
      label={label}
      value={
        <>
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="tf-tnum">Hasta el {formatDate(vigencia.fecha_fin)}</span>
            <FechaFinOrigenBadge origen={vigencia.origen} />
          </span>
          {dias != null ? (
            <span className={NOTA}>
              {dias >= 0
                ? `${dias === 1 ? "Queda" : "Quedan"} ${contar(dias, "día", "días")}`
                : `Venció hace ${contar(-dias, "día", "días")}`}
            </span>
          ) : null}
        </>
      }
    />
  );
}
