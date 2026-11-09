"use client";

/**
 * El acuerdo marco o el sistema dinámico de adquisición de un expediente.
 *
 * En un marco o un SDA: cuántas empresas están admitidas, si la tuya es una de
 * ellas y hasta cuándo está vivo (`GET /licitaciones/{id}/marco`; todo viene
 * calculado, aquí no se cuenta nada, ADR-014). La fecha es la misma que enseña
 * Renovaciones en Mercado.
 *
 * En un contrato basado solo se dice que lo es: ninguna fuente publica de qué
 * marco cuelga, así que los admitidos que compiten van como «sin dato», nunca
 * como cero. Por eso un basado no pide nada a la API.
 *
 * Un expediente corriente, o uno cuya fuente no dice qué es, no pinta nada.
 */

import * as React from "react";
import Link from "next/link";
import { Fact, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { FechaFinOrigenBadge } from "@/components/pursuits/fecha-fin-origen-badge";
import { useMarco } from "@/hooks/use-licitacion";
import type { MarcoDeLicitacion } from "@/lib/api-types";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import { ETIQUETA_SISTEMA, esMarco, sistemaRotulado, type SistemaRotulado } from "@/lib/sistema-contratacion";
import { formatDate, formatNumber } from "@/lib/utils";

const REJILLA = "border-divider bg-divider grid gap-px overflow-hidden rounded-md border";
const NOTA = "text-muted-foreground text-tf-meta block font-normal text-pretty";

function contar(n: number, singular: string, plural: string): string {
  return `${formatNumber(n)} ${n === 1 ? singular : plural}`;
}

function lotesDe(lotes: string[]): string | null {
  if (lotes.length === 0) return null;
  return lotes.length === 1 ? `Lote ${lotes[0]}` : `Lotes ${lotes.join(", ")}`;
}

/** Un valor que la fuente no da, con el motivo debajo. */
function SinDato({ children }: { children: React.ReactNode }) {
  return (
    <>
      Sin dato
      <span className={NOTA}>{children}</span>
    </>
  );
}

export function FichaMarco({ licitacion: l }: { licitacion: LicitacionDetail }) {
  const sistema = sistemaRotulado(l.sistema_contratacion);
  if (!sistema) return null;
  return esMarco(sistema) ? <Marco licitacionId={l.id_externo} sistema={sistema} /> : <Basado sistema={sistema} />;
}

function Basado({ sistema }: { sistema: "basado_marco" | "basado_sda" }) {
  const id = React.useId();
  const [elMarco, delMarco] =
    sistema === "basado_marco"
      ? ["el acuerdo marco", "de qué acuerdo marco"]
      : ["el sistema dinámico", "de qué sistema dinámico"];
  return (
    <section aria-labelledby={id}>
      <PanelTitle as="h3" id={id} title={ETIQUETA_SISTEMA[sistema]} />
      <p className="text-tf-body mb-3 text-pretty">
        Solo pueden presentar oferta las empresas ya admitidas en {elMarco}.
      </p>
      <div className={REJILLA}>
        <Fact
          label="Admitidos que compiten"
          value={
            <SinDato>
              La fuente no publica {delMarco} cuelga este contrato. El título o el pliego suelen nombrarlo.
            </SinDato>
          }
        />
        <Fact
          label="Tu organización"
          value={<SinDato>Sin saber cuál es, no se puede decir si estás entre sus admitidos.</SinDato>}
        />
      </div>
    </section>
  );
}

function Marco({ licitacionId, sistema }: { licitacionId: string; sistema: "marco" | "sda" }) {
  const id = React.useId();
  const { data, isPending, error, refetch } = useMarco(licitacionId);
  const titulo = <PanelTitle as="h3" id={id} title={ETIQUETA_SISTEMA[sistema]} hint="Admitidos y vigencia" />;

  if (isPending || error || !data) {
    return (
      <section aria-labelledby={id}>
        {titulo}
        {isPending ? (
          <PanelLoading height={96} />
        ) : (
          <PanelError
            variant="inline"
            title="No se pudieron cargar los admitidos"
            error={error}
            onRetry={() => void refetch()}
          />
        )}
      </section>
    );
  }

  const total = data.admitidos_total ?? 0;
  const admitidos = data.admitidos ?? [];
  return (
    <section aria-labelledby={id}>
      {titulo}
      <div className={REJILLA}>
        <Fact
          label="Empresas admitidas"
          value={
            total > 0 ? (
              <span className="tf-tnum">{contar(total, "empresa", "empresas")}</span>
            ) : (
              <SinDato>La fuente no ha publicado admitidos. Aparecen cuando se adjudica.</SinDato>
            )
          }
        />
        <TuOrganizacion marco={data} />
        <Vigencia vigencia={data.vigencia} />
        <Fact
          label="Contratos basados"
          value={<SinDato>Las fuentes no publican de qué {nombreCorto(sistema)} cuelga cada contrato basado.</SinDato>}
        />
      </div>
      {total > 0 ? (
        <details className="text-tf-meta mt-3">
          <summary className="text-primary w-fit cursor-pointer rounded-sm font-medium hover:underline">
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
      ) : null}
    </section>
  );
}

function nombreCorto(sistema: SistemaRotulado): string {
  return sistema === "sda" || sistema === "basado_sda" ? "sistema dinámico" : "acuerdo marco";
}

function TuOrganizacion({ marco }: { marco: MarcoDeLicitacion }) {
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

function Vigencia({ vigencia }: { vigencia: MarcoDeLicitacion["vigencia"] }) {
  const label = "Vigencia";
  if (!vigencia?.fecha_fin) {
    return <Fact label={label} value={<SinDato>La fuente no publica fecha de fin ni duración.</SinDato>} />;
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
