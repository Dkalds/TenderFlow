"use client";

import * as React from "react";
import { ExternalLink } from "lucide-react";
import { Aviso, ROTULO_DATO, SectionTitle } from "@/components/console/panel";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { Badge } from "@/components/ui/badge";
import type {
  CondicionesAmbito,
  CondicionesOficiales,
  CriterioOficial,
  GarantiaOficial,
  RequisitoSolvenciaOficial,
} from "@/hooks/use-condiciones-oficiales";
import { formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/utils";

/**
 * v148 — criterios, garantías y solvencia tal como los publica PLACSP.
 *
 * Es la fuente primaria de esas familias y por eso va primero en la pestaña
 * Pliego, con su procedencia a la vista y el enlace para comprobarla. Todo lo
 * que se pinta viene resuelto de `GET /condiciones-oficiales` (ADR-014):
 *
 * - El peso se enseña como porcentaje **solo** si la API lo trae en
 *   `peso_pct`, que es cuando la escala del ámbito se pudo deducir. Si no, el
 *   peso publicado tal cual: un «70 %» sobre un denominador que nadie publicó
 *   sería un dato inventado.
 * - Los códigos de tipo no se traducen: la API no trae su etiqueta.
 * - Un subcriterio va debajo de su criterio, sin porcentaje propio.
 */

const SOLVENCIA: Array<{ clase: RequisitoSolvenciaOficial["clase"]; titulo: string; vacio: string }> = [
  { clase: "tecnica", titulo: "Solvencia técnica", vacio: "Requisito de solvencia técnica" },
  { clase: "economica", titulo: "Solvencia económica", vacio: "Requisito de solvencia económica" },
  { clase: "clasificacion", titulo: "Clasificación empresarial", vacio: "Clasificación exigida" },
];

function porcentaje(valor: number): string {
  return formatPercent(valor, Number.isInteger(valor) ? 0 : 1);
}

/** Un código de moneda mal formado haría lanzar a `Intl`: se cae al euro. */
function importe(valor: number, moneda: string | null | undefined): string {
  return formatCurrency(valor, "es-ES", moneda && /^[A-Z]{3}$/.test(moneda) ? moneda : "EUR");
}

function Criterio({ criterio, hijos }: { criterio: CriterioOficial; hijos: CriterioOficial[] }) {
  const peso =
    criterio.peso_pct != null
      ? porcentaje(criterio.peso_pct)
      : criterio.peso != null
        ? `Peso publicado: ${formatNumber(criterio.peso)}`
        : null;
  return (
    <li className="rounded-md border border-border/70 bg-background p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="min-w-0 text-tf-body font-medium leading-snug">
          {criterio.descripcion ?? "Criterio sin descripción"}
        </p>
        <div className="flex flex-none flex-wrap gap-1.5">
          {criterio.es_precio && (
            <Badge size="sm" variant="info">
              Precio
            </Badge>
          )}
          {peso && (
            <Badge size="sm" className="tf-tnum">
              {peso}
            </Badge>
          )}
        </div>
      </div>
      {criterio.nota && <p className="mt-1 text-tf-meta text-muted-foreground">{criterio.nota}</p>}
      {hijos.length > 0 && (
        <ul className="mt-2 space-y-1.5 border-l border-border/60 pl-3">
          {hijos.map((hijo) => (
            <li key={hijo.orden} className="flex flex-wrap items-baseline justify-between gap-2 text-tf-meta">
              <span>{hijo.descripcion ?? "Subcriterio sin descripción"}</span>
              {hijo.peso != null && (
                <span className="tf-tnum text-muted-foreground">
                  Peso publicado: {formatNumber(hijo.peso)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function Garantia({ garantia }: { garantia: GarantiaOficial }) {
  const cifras = [
    garantia.porcentaje != null ? porcentaje(garantia.porcentaje) : null,
    garantia.importe != null ? importe(garantia.importe, garantia.moneda) : null,
  ].filter((valor): valor is string => valor != null);
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-2 rounded-md border border-border/70 bg-background px-3 py-2">
      <span className="text-tf-body">
        {cifras.length > 0 ? (
          <span className="tf-tnum font-medium">{cifras.join(" · ")}</span>
        ) : (
          (garantia.descripcion ?? "Garantía exigida")
        )}
        {cifras.length > 0 && garantia.descripcion && (
          <span className="ml-2 text-tf-meta text-muted-foreground">{garantia.descripcion}</span>
        )}
      </span>
      {garantia.tipo_codigo && <span className={ROTULO_DATO}>Tipo {garantia.tipo_codigo}</span>}
    </li>
  );
}

function Requisito({ requisito, vacio }: { requisito: RequisitoSolvenciaOficial; vacio: string }) {
  const texto =
    requisito.clase === "clasificacion"
      ? [requisito.tipo_codigo, requisito.descripcion].filter(Boolean).join(" · ") || vacio
      : (requisito.descripcion ?? vacio);
  return (
    <li className="rounded-md border border-border/70 bg-background px-3 py-2">
      <p className="text-tf-body leading-snug">{texto}</p>
      {requisito.umbral_importe != null && (
        <p className="tf-tnum mt-1 text-tf-meta text-muted-foreground">
          Umbral {importe(requisito.umbral_importe, requisito.moneda)}
        </p>
      )}
    </li>
  );
}

function Grupo({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div>
      <p className={`mb-1.5 ${ROTULO_DATO}`}>{titulo}</p>
      <ul className="space-y-2">{children}</ul>
    </div>
  );
}

function Ambito({ ambito }: { ambito: CondicionesAmbito }) {
  const id = React.useId();
  const criterios = ambito.criterios ?? [];
  const garantias = ambito.garantias ?? [];
  const solvencia = ambito.solvencia ?? [];
  const raiz = criterios.filter((c) => c.padre_orden == null);
  const titulo =
    ambito.lote_numero == null
      ? "Expediente"
      : [`Lote ${ambito.lote_numero}`, ambito.lote_titulo].filter(Boolean).join(" · ");
  return (
    <section aria-labelledby={id} className="space-y-3">
      <h5 id={id} className="text-tf-body font-semibold">
        {titulo}
      </h5>
      {raiz.length > 0 && (
        <Grupo titulo="Criterios de adjudicación">
          {raiz.map((criterio) => (
            <Criterio
              key={criterio.orden}
              criterio={criterio}
              hijos={criterios.filter((c) => c.padre_orden === criterio.orden)}
            />
          ))}
        </Grupo>
      )}
      {garantias.length > 0 && (
        <Grupo titulo="Garantías">
          {garantias.map((garantia) => (
            <Garantia key={garantia.orden} garantia={garantia} />
          ))}
        </Grupo>
      )}
      {SOLVENCIA.map(({ clase, titulo: rotulo, vacio }) => {
        const deClase = solvencia.filter((r) => r.clase === clase);
        return deClase.length > 0 ? (
          <Grupo key={clase} titulo={rotulo}>
            {deClase.map((requisito) => (
              <Requisito key={requisito.orden} requisito={requisito} vacio={vacio} />
            ))}
          </Grupo>
        ) : null;
      })}
    </section>
  );
}

export function CondicionesOficialesBloque({
  datos,
  licitacionId,
}: {
  datos: CondicionesOficiales;
  licitacionId: string;
}) {
  const ambitos = datos.ambitos ?? [];
  if (ambitos.length === 0) return null;
  return (
    <div className="space-y-4">
      <SectionTitle
        hint={datos.actualizado ? `Leída el ${formatDate(datos.actualizado)}` : undefined}
        className="mb-1"
      >
        Publicación oficial (PLACSP)
      </SectionTitle>
      {datos.url_publicacion && (
        <a
          href={datos.url_publicacion}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-tf-meta font-medium text-primary hover:underline"
        >
          Ver la publicación en PLACSP
          <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
          <AvisoPestanaNueva />
        </a>
      )}
      {datos.licitacion_id !== licitacionId && (
        <Aviso tone="info" role="note">
          Es la publicación oficial del expediente original {datos.licitacion_id}: esta licitación
          es su republicación.
        </Aviso>
      )}
      {ambitos.map((ambito) => (
        <Ambito key={ambito.lote_numero ?? "expediente"} ambito={ambito} />
      ))}
    </div>
  );
}
