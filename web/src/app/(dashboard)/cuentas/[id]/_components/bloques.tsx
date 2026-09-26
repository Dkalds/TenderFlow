"use client";

/**
 * Los tres bloques de la ficha de una cuenta: publicaciones recientes,
 * contratos que vencen y oportunidades del equipo.
 *
 * Todo lo que enseñan lo calcula el backend (`GET /cuentas/{id}`, ADR-014), y
 * cada bloque dice a la vista **sobre qué universo y en qué ventana** cuenta:
 * es el criterio de aceptación de F1.5, y es lo que impide leer «3
 * publicaciones» como «el cliente sólo publicó tres cosas». Cuando el bloque
 * trae menos filas que su total, lo dice.
 */

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Panel, PanelEmpty, SectionTitle } from "@/components/console/panel";
import { statusLabel } from "@/components/pursuits/pursuit-presenters";
import type { PursuitStatus } from "@/hooks/use-pursuits";
import type { AmbitoCifra, FichaCuenta } from "@/hooks/use-cuentas";
import { formatCurrency, formatDate, formatNumber } from "@/lib/utils";

function Ambito({ ambito }: { ambito: AmbitoCifra }) {
  return (
    <p className="-mt-1 mb-3 text-tf-micro leading-relaxed text-muted-foreground">
      {ambito.ventana} {ambito.universo}
    </p>
  );
}

function Resto({ total, mostradas, nombre }: { total: number; mostradas: number; nombre: string }) {
  if (total <= mostradas) return null;
  return (
    <p className="mt-2 text-tf-micro text-muted-foreground">
      Se muestran {mostradas} de {formatNumber(total)} {nombre}.
    </p>
  );
}

/** ADR-032 §A: el importe es la base sin IVA, y se dice cuándo no se sabe. */
function importeConBase(importe: number | null | undefined, tipo: string | null | undefined) {
  if (importe == null) return null;
  const base = tipo === "sin_iva" ? " sin IVA" : tipo === "con_iva" ? " con IVA" : "";
  return `${formatCurrency(importe)}${base}`;
}

export function BloquePublicaciones({ bloque }: { bloque: FichaCuenta["publicaciones"] }) {
  const items = bloque.items ?? [];
  return (
    <Panel>
      <SectionTitle aside={<span className="tabular-nums">{formatNumber(bloque.total)}</span>}>
        Publicaciones recientes
      </SectionTitle>
      <Ambito ambito={bloque.ambito} />
      {items.length === 0 ? (
        <PanelEmpty message="Sus órganos no han publicado nada en la ventana." height={96} />
      ) : (
        <ul className="flex flex-col divide-y divide-border/50">
          {items.map((publicacion) => (
            <li key={publicacion.id_externo} className="py-2 first:pt-0 last:pb-0">
              <div className="flex items-start justify-between gap-2">
                <Link
                  href={`/detalle?lic=${encodeURIComponent(publicacion.id_externo)}`}
                  className="text-sm leading-tight font-medium hover:underline"
                >
                  {publicacion.titulo ?? publicacion.id_externo}
                </Link>
                {publicacion.abierta && (
                  <Badge variant="secondary" className="flex-none">
                    Abierta
                  </Badge>
                )}
              </div>
              <p className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                {publicacion.organo && <span>{publicacion.organo}</span>}
                {importeConBase(publicacion.importe, publicacion.importe_tipo) && (
                  <span className="text-foreground">
                    {importeConBase(publicacion.importe, publicacion.importe_tipo)}
                  </span>
                )}
                <span>
                  Publicada {formatDate(publicacion.fecha_publicacion ?? publicacion.primera_extraccion)}
                </span>
                {publicacion.fecha_limite && <span>Plazo {formatDate(publicacion.fecha_limite)}</span>}
              </p>
            </li>
          ))}
        </ul>
      )}
      <Resto total={bloque.total} mostradas={items.length} nombre="publicaciones" />
    </Panel>
  );
}

export function BloqueVencimientos({ bloque }: { bloque: FichaCuenta["vencimientos"] }) {
  const items = bloque.items ?? [];
  return (
    <Panel>
      <SectionTitle aside={<span className="tabular-nums">{formatNumber(bloque.total)}</span>}>
        Contratos que vencen
      </SectionTitle>
      <Ambito ambito={bloque.ambito} />
      {items.length === 0 ? (
        <PanelEmpty message="Ningún contrato de sus órganos vence en la ventana." height={96} />
      ) : (
        <ul className="flex flex-col divide-y divide-border/50">
          {items.map((contrato, indice) => (
            <li
              key={`${contrato.licitacion_id}-${contrato.empresa_id ?? contrato.empresa ?? indice}`}
              className="py-2 first:pt-0 last:pb-0"
            >
              <Link
                href={`/detalle?lic=${encodeURIComponent(contrato.licitacion_id)}`}
                className="text-sm leading-tight font-medium hover:underline"
              >
                {contrato.titulo ?? contrato.licitacion_id}
              </Link>
              <p className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                <span className="text-foreground">
                  Fin {formatDate(contrato.fecha_fin)}
                  {contrato.fecha_fin_origen !== "real" && " (estimado)"}
                </span>
                {contrato.empresa &&
                  (contrato.empresa_id != null ? (
                    <Link
                      href={`/competencia/empresa/${contrato.empresa_id}`}
                      className="hover:underline"
                    >
                      Lo tiene {contrato.empresa}
                    </Link>
                  ) : (
                    <span>Lo tiene {contrato.empresa}</span>
                  ))}
                {contrato.importe_adjudicado != null && (
                  <span>{formatCurrency(contrato.importe_adjudicado)} adjudicados</span>
                )}
                {contrato.organo && <span>{contrato.organo}</span>}
              </p>
            </li>
          ))}
        </ul>
      )}
      <Resto total={bloque.total} mostradas={items.length} nombre="contratos" />
    </Panel>
  );
}

export function BloqueOportunidades({ bloque }: { bloque: FichaCuenta["oportunidades"] }) {
  const items = bloque.items ?? [];
  return (
    <Panel>
      <SectionTitle
        aside={
          <span className="tabular-nums">
            {formatNumber(bloque.activas)} {bloque.activas === 1 ? "activa" : "activas"}
          </span>
        }
      >
        Oportunidades del equipo
      </SectionTitle>
      <Ambito ambito={bloque.ambito} />
      {items.length === 0 ? (
        <PanelEmpty
          message="El equipo no tiene oportunidades en expedientes de esta cuenta."
          height={96}
        />
      ) : (
        <ul className="flex flex-col divide-y divide-border/50">
          {items.map((oportunidad) => (
            <li key={oportunidad.id} className="py-2 first:pt-0 last:pb-0">
              <div className="flex items-start justify-between gap-2">
                <Link
                  href={`/oportunidades/${oportunidad.id}`}
                  className="text-sm leading-tight font-medium hover:underline"
                >
                  {oportunidad.titulo ?? oportunidad.licitacion_id}
                  {oportunidad.lote_numero && ` · lote ${oportunidad.lote_numero}`}
                </Link>
                <Badge variant={oportunidad.activa ? "secondary" : "outline"} className="flex-none">
                  {statusLabel(oportunidad.status as PursuitStatus) ?? oportunidad.status}
                </Badge>
              </div>
              <p className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                {oportunidad.activa &&
                  (oportunidad.next_action ? (
                    <span className="text-foreground">
                      Próxima acción: {oportunidad.next_action}
                      {oportunidad.next_action_due && ` · ${formatDate(oportunidad.next_action_due)}`}
                    </span>
                  ) : (
                    <span>Sin próxima acción</span>
                  ))}
                <span>{oportunidad.responsable ?? "Sin responsable"}</span>
              </p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
