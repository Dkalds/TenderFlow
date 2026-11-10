"use client";

/**
 * El acuerdo marco o el sistema dinámico de adquisición de un expediente
 * (`GET /licitaciones/{id}/marco`; todo viene calculado, aquí no se cuenta
 * nada, ADR-014).
 *
 * En un marco o un SDA: cuántas empresas están admitidas, si la tuya es una de
 * ellas, hasta cuándo está vivo —la fecha de Renovaciones en Mercado— y los
 * contratos basados que lo citan.
 *
 * En un contrato basado: los admitidos de su marco, que son los que compiten.
 * Solo si la fuente publica cuál es su marco y ese marco está aquí; si no, van
 * como «sin dato», nunca como cero, y el marco no se deduce del título.
 *
 * Un expediente corriente, o uno cuya fuente no dice qué es, no pinta nada ni
 * pide nada.
 */

import * as React from "react";
import { EnlaceFicha } from "@/components/ficha/enlace-ficha";
import {
  Admitidos,
  DESPLEGABLE,
  ListaDeAdmitidos,
  NOTA,
  REJILLA,
  SinDato,
  TuOrganizacion,
  Vigencia,
  contar,
} from "@/components/ficha/ficha-marco-celdas";
import { Fact, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { useMarco } from "@/hooks/use-licitacion";
import type { MarcoDeLicitacion } from "@/lib/api-types";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import { ETIQUETA_SISTEMA, esMarco, sistemaRotulado, type SistemaRotulado } from "@/lib/sistema-contratacion";
import { formatCurrency, formatDate, formatNumber } from "@/lib/utils";

/** «acuerdo marco» o «sistema dinámico», para hablar del marco de cualquiera de los cuatro. */
function nombreCorto(sistema: SistemaRotulado): string {
  return sistema === "sda" || sistema === "basado_sda" ? "sistema dinámico" : "acuerdo marco";
}

export function FichaMarco({ licitacion: l }: { licitacion: LicitacionDetail }) {
  const sistema = sistemaRotulado(l.sistema_contratacion);
  if (!sistema) return null;
  return <Bloque licitacionId={l.id_externo} sistema={sistema} />;
}

function Bloque({ licitacionId, sistema }: { licitacionId: string; sistema: SistemaRotulado }) {
  const id = React.useId();
  const { data, isPending, error, refetch } = useMarco(licitacionId);
  const titulo = <PanelTitle as="h3" id={id} title={ETIQUETA_SISTEMA[sistema]} />;

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

  return (
    <section aria-labelledby={id}>
      {titulo}
      {esMarco(sistema) ? <Marco marco={data} sistema={sistema} /> : <Basado marco={data} sistema={sistema} />}
    </section>
  );
}

function Marco({ marco, sistema }: { marco: MarcoDeLicitacion; sistema: SistemaRotulado }) {
  const basados = marco.basados ?? [];
  return (
    <>
      <div className={REJILLA}>
        <Admitidos marco={marco} label="Empresas admitidas" esSda={sistema === "sda"} />
        <TuOrganizacion marco={marco} />
        <Vigencia vigencia={marco.vigencia} label="Vigencia" />
        <Fact
          label="Contratos basados"
          value={
            marco.basados_total != null ? (
              <>
                <span className="tf-tnum">
                  {contar(marco.basados_total, "contrato lo cita", "contratos lo citan")}
                </span>
                <span className={NOTA}>Solo los que su fuente enlaza con el {nombreCorto(sistema)}.</span>
              </>
            ) : (
              <SinDato>
                Ningún contrato basado de los que hay aquí lo cita. PLACSP no publica de qué {nombreCorto(sistema)}{" "}
                cuelga cada uno.
              </SinDato>
            )
          }
        />
      </div>
      <ListaDeAdmitidos marco={marco} />
      {marco.basados_total != null && basados.length > 0 ? (
        <details className="text-tf-meta mt-2">
          <summary className={DESPLEGABLE}>
            Ver {marco.basados_total === 1 ? "el contrato basado" : "los contratos basados"}
          </summary>
          <ul className="divide-divider mt-1 divide-y">
            {basados.map((basado) => (
              <li key={basado.licitacion_id} className="py-2">
                <EnlaceFicha
                  idExterno={basado.licitacion_id}
                  className="text-tf-body hover:text-primary font-medium text-pretty"
                >
                  {basado.titulo}
                </EnlaceFicha>
                <p className="text-muted-foreground text-pretty">
                  {[
                    basado.organo_contratacion,
                    basado.importe != null ? formatCurrency(basado.importe) : null,
                    basado.fecha_publicacion ? `publicado el ${formatDate(basado.fecha_publicacion)}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </li>
            ))}
          </ul>
          {marco.basados_total > basados.length ? (
            <p className="text-muted-foreground mt-1">
              Son los {formatNumber(basados.length)} más recientes de {formatNumber(marco.basados_total)}.
            </p>
          ) : null}
        </details>
      ) : null}
    </>
  );
}

function Basado({ marco, sistema }: { marco: MarcoDeLicitacion; sistema: SistemaRotulado }) {
  const elMarco = `el ${nombreCorto(sistema)}`;
  const intro = (
    <p className="text-tf-body mb-3 text-pretty">Solo pueden presentar oferta las empresas ya admitidas en {elMarco}.</p>
  );

  if (!marco.marco) {
    return (
      <>
        {intro}
        <div className={REJILLA}>
          <Fact
            label="Admitidos que compiten"
            value={
              marco.marco_referencia ? (
                <SinDato>
                  Su marco es el aviso {marco.marco_referencia}, que no está aquí: no es de tecnología o es anterior
                  a lo recogido.
                </SinDato>
              ) : (
                <SinDato>
                  La fuente no publica de qué {nombreCorto(sistema)} cuelga este contrato. El título o el pliego
                  suelen nombrarlo.
                </SinDato>
              )
            }
          />
          <Fact
            label="Tu organización"
            value={<SinDato>Sin los admitidos de su marco no se puede decir si estás entre ellos.</SinDato>}
          />
        </div>
      </>
    );
  }

  return (
    <>
      {intro}
      <div className={REJILLA}>
        <Fact
          label={`Su ${nombreCorto(sistema)}`}
          value={
            <>
              <EnlaceFicha idExterno={marco.marco.licitacion_id} className="hover:text-primary text-pretty underline">
                {marco.marco.titulo}
              </EnlaceFicha>
              {marco.marco.organo_contratacion ? (
                <span className={NOTA}>{marco.marco.organo_contratacion}</span>
              ) : null}
            </>
          }
        />
        {marco.admitidos_total == null ? (
          <Fact
            label="Admitidos que compiten"
            value={<SinDato>Todavía no se conocen los admitidos de su {nombreCorto(sistema)}.</SinDato>}
          />
        ) : (
          <>
            <Admitidos marco={marco} label="Admitidos que compiten" esSda={marco.marco.sistema === "sda"} />
            <TuOrganizacion marco={marco} />
            <Vigencia vigencia={marco.vigencia} label={`Vigencia del ${nombreCorto(sistema)}`} />
          </>
        )}
      </div>
      <ListaDeAdmitidos marco={marco} />
    </>
  );
}
