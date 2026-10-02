"use client";

/**
 * F3.3 — con quién ir a una UTE en el segmento de este expediente.
 *
 * `services/partners.py` llevaba meses con funciones sin consumidor; el backend
 * ya las sirve (`GET /competitive/partners`) con lo que convierte un ranking en
 * una sugerencia: **el motivo** de cada empresa, redactado en servidor y citando
 * el dato que lo sostiene. Aquí sólo se pinta, con tres reglas que vienen del
 * contrato:
 *
 * - **Socios y líderes van separados.** Los líderes son con quién se compite,
 *   no con quién aliarse; mezclarlos haría parecer que el producto propone
 *   asociarse con el que domina el segmento.
 * - **Sin base suficiente, lista vacía declarada** (`sin_resultados`), no un
 *   relleno con las empresas más grandes.
 * - **El universo se dice**: `n_adjudicaciones` es el `n` sobre el que se
 *   calculó (ADR-014).
 *
 * El segmento sale del propio expediente: el CPV por prefijo —el código sin
 * los ceros de cola, que en la nomenclatura CPV marcan el nivel— y la CCAA.
 */

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { PanelEmpty, PanelError, PanelLoading, SectionTitle } from "@/components/console/panel";
import { registrarEvento } from "@/lib/analytics";
import { apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { competitiveKeys } from "@/lib/query-keys";
import { formatCompactCurrency, formatNumber, formatPercent } from "@/lib/utils";

type SugerenciaSocios = Schemas["SugerenciaSocios"];

/** Sugerencias pedidas: las que se leen en una columna lateral. */
const LIMITE = 5;

/**
 * Prefijo CPV del segmento a partir del CPV del expediente.
 *
 * El expediente puede traer varios códigos (CSV) y con dígito de control
 * (`72212000-4`); se toma el primero, sus ocho dígitos y se quitan los ceros de
 * cola, que en CPV significan «todo lo que cuelga de aquí». El backend exige
 * entre 2 y 8 dígitos; con menos de dos no hay segmento que pedir.
 */
export function prefijoCpv(cpv: string | null | undefined): string | null {
  const primero = (cpv ?? "").split(/[,;\s]+/).find((codigo) => /\d/.test(codigo));
  if (!primero) return null;
  const digitos = primero.replace(/\D/g, "").slice(0, 8);
  if (digitos.length < 2) return null;
  const sinCeros = digitos.replace(/0+$/, "");
  return sinCeros.length >= 2 ? sinCeros : digitos.slice(0, 2);
}

function useSociosUte(cpv: string | null, ccaa: string | null) {
  return useQuery<SugerenciaSocios>({
    queryKey: competitiveKeys.partners(cpv, ccaa),
    queryFn: () =>
      apiGet("/api/v1/competitive/partners", {
        params: { query: { cpv: cpv ?? undefined, ccaa: ccaa ?? undefined, limit: LIMITE } },
      }),
    enabled: cpv != null,
    staleTime: 10 * 60_000,
    // El fallo se dice en el panel (PanelError): sin toast además.
    meta: META_ERROR_EN_LINEA,
  });
}

/** Enlace al dossier sólo cuando la clave es un id del maestro. */
function Empresa({ nombre, clave }: { nombre: string; clave: string }) {
  if (/^\d+$/.test(clave)) {
    return (
      <Link href={`/competencia/empresa/${clave}`} className="font-medium transition-colors hover:text-primary">
        {nombre}
      </Link>
    );
  }
  return <span className="font-medium">{nombre}</span>;
}

export function SociosUte({ cpv, ccaa }: { cpv: string | null | undefined; ccaa: string | null | undefined }) {
  const prefijo = prefijoCpv(cpv);
  const region = ccaa?.trim() ? ccaa.trim() : null;
  const { data, isLoading, error, refetch } = useSociosUte(prefijo, region);
  const medida = React.useRef(false);

  React.useEffect(() => {
    if (!data || medida.current) return;
    medida.current = true;
    registrarEvento("partners_consultado", { con_resultados: (data.socios ?? []).length > 0 ? "si" : "no" });
  }, [data]);

  if (prefijo == null) {
    return (
      <PanelEmpty
        size="sm"
        title="Sin socios que sugerir"
        hint="El expediente no trae CPV: sin segmento no hay socios que sugerir."
      />
    );
  }
  if (isLoading) return <PanelLoading height={160} />;
  if (error || !data) {
    return (
      <PanelError
        title="No se pudieron cargar los socios sugeridos"
        error={error ?? undefined}
        onRetry={() => void refetch()}
      />
    );
  }

  const socios = data.socios ?? [];
  const lideres = data.lideres ?? [];
  const segmento = `CPV ${prefijo}${region ? ` · ${region}` : ""}`;

  return (
    <div className="space-y-3 text-tf-meta">
      <p className="text-tf-micro text-muted-foreground">
        Segmento {segmento} · sobre {formatNumber(data.n_adjudicaciones)} adjudicaciones
      </p>

      {socios.length === 0 ? (
        <PanelEmpty size="sm" hint={data.sin_resultados ?? "Sin empresas que sugerir en este segmento."} />
      ) : (
        <ul className="flex flex-col gap-2.5" aria-label="Socios sugeridos">
          {socios.map((socio) => (
            <li key={socio.empresa_key} className="rounded-md border border-border/60 px-2.5 py-2">
              <div className="flex items-baseline justify-between gap-2">
                <Empresa nombre={socio.empresa} clave={socio.empresa_key} />
                <span className="flex-none text-tf-micro text-muted-foreground">
                  {formatNumber(socio.n_contratos)} contratos
                </span>
              </div>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-tf-meta text-muted-foreground">
                {socio.motivos.map((motivo) => (
                  <li key={motivo}>{motivo}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}

      {lideres.length > 0 && (
        <div>
          <SectionTitle className="mb-1">Quién manda en el segmento</SectionTitle>
          <p className="mb-1.5 text-tf-micro text-muted-foreground">
            No son socios sugeridos: son contra quién se compite.
          </p>
          <ul className="flex flex-col gap-1" aria-label="Líderes del segmento">
            {lideres.map((lider) => (
              <li key={lider.empresa_key} className="flex items-baseline justify-between gap-2">
                <Empresa nombre={lider.empresa} clave={lider.empresa_key} />
                <span className="flex-none text-tf-micro text-muted-foreground">
                  {formatPercent(lider.cuota_pct)} · {formatCompactCurrency(lider.importe_total)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
