"use client";

/**
 * Pestaña «Identidad» del dossier: quién es la empresa en el maestro.
 *
 * Es lo que la ficha de `/empresas` enseñaba y el dossier no: NIF canónico,
 * grupo, alias vistos en fuente y relaciones de UTE. No depende del ámbito ni
 * del periodo —es el registro, no la actividad—, así que no los lee.
 *
 * Cuando la ficha suma varias identidades del maestro, dice cuáles. Competencia
 * agrupa como un solo competidor las que comparten NIF o nombre normalizado
 * (`_prepare_company_identity` en `services/analytics/competitors.py`), sin
 * fusionarlas en el maestro, que las conserva por separado. Sin esta pestaña,
 * las cifras del dossier y las de cada fila del maestro no cuadraban y nada
 * explicaba por qué.
 *
 * La consulta es la misma que usa `/empresas` (`empresasKeys.detail`), así que
 * las dos pantallas comparten caché.
 */

import Link from "next/link";
import { useQueries, type UseQueryResult } from "@tanstack/react-query";

import { PanelError } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { empresasKeys } from "@/lib/query-keys";
import { formatNumber } from "@/lib/utils";

type EmpresaDetalle = Schemas["EmpresaDetail"];

/** Alias que se pintan antes de resumir el resto en «+N más». */
const ALIAS_VISIBLES = 12;

export function CompanyIdentidad({ empresaIds }: { empresaIds: number[] }) {
  const consultas = useQueries({
    queries: empresaIds.map((empresaId) => ({
      queryKey: empresasKeys.detail(empresaId),
      queryFn: () => fetchWithAuth<EmpresaDetalle>(`/api/v1/empresas/${empresaId}`),
      staleTime: 5 * 60 * 1000,
    })),
  });

  return (
    <section aria-labelledby="identidad-titulo" className="space-y-4">
      <h2 id="identidad-titulo" className="sr-only">
        Identidad en el maestro
      </h2>
      {empresaIds.length > 1 && (
        <p className="text-muted-foreground max-w-3xl text-sm leading-6">
          Esta ficha suma {formatNumber(empresaIds.length)} identidades del maestro. Competencia las cuenta como un solo
          competidor porque comparten NIF o nombre normalizado; el maestro las conserva por separado.
        </p>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        {consultas.map((consulta, indice) => (
          <IdentidadTarjeta key={empresaIds[indice]} empresaId={empresaIds[indice]} consulta={consulta} />
        ))}
      </div>
    </section>
  );
}

function IdentidadTarjeta({ empresaId, consulta }: { empresaId: number; consulta: UseQueryResult<EmpresaDetalle> }) {
  if (consulta.isLoading) return <Skeleton className="h-44 w-full rounded-lg" />;
  if (consulta.isError || !consulta.data) {
    return (
      <PanelError
        title="No se pudo cargar esta identidad"
        detail={`GET /api/v1/empresas/${empresaId}`}
        onRetry={() => void consulta.refetch()}
      />
    );
  }

  const empresa = consulta.data;
  // Los NIF con los que la empresa aparece en fuente además del canónico: son
  // los que explican que Competencia la junte con otra identidad.
  const otrosNif = [
    ...new Set(
      empresa.aliases
        .map((alias) => alias.nif_variante)
        .filter((nif): nif is string => Boolean(nif) && nif !== empresa.nif_canonico),
    ),
  ];
  const aliasOcultos = empresa.aliases.length - ALIAS_VISIBLES;
  const tituloId = `identidad-${empresa.empresa_id}`;

  return (
    <section aria-labelledby={tituloId} className="bg-card space-y-4 rounded-lg border p-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h3 id={tituloId} className="font-semibold">
            {empresa.nombre_canonico}
          </h3>
          {empresa.es_ute ? <Badge variant="info">UTE</Badge> : null}
          {empresa.es_pyme ? <Badge variant="secondary">PYME</Badge> : null}
        </div>
        <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-muted-foreground">NIF</dt>
          <dd className="font-mono">{empresa.nif_canonico ?? "Sin NIF canónico"}</dd>
          {otrosNif.length > 0 && (
            <>
              <dt className="text-muted-foreground">Otros NIF en fuente</dt>
              <dd className="font-mono">{otrosNif.join(", ")}</dd>
            </>
          )}
          {empresa.grupo && (
            <>
              <dt className="text-muted-foreground">Grupo</dt>
              <dd>{empresa.grupo}</dd>
            </>
          )}
          <dt className="text-muted-foreground">Id del maestro</dt>
          <dd className="font-mono">{empresa.empresa_id}</dd>
        </dl>
      </div>

      {empresa.aliases.length > 0 && (
        <div>
          <h4 className="text-muted-foreground mb-2 text-xs font-semibold tracking-[0.12em] uppercase">
            Alias vistos en fuente ({formatNumber(empresa.aliases.length)})
          </h4>
          <ul className="flex flex-wrap gap-1.5">
            {empresa.aliases.slice(0, ALIAS_VISIBLES).map((alias, indice) => (
              <li
                key={`${alias.alias_normalizado}-${indice}`}
                className="bg-muted text-muted-foreground rounded px-2 py-0.5 font-mono text-xs"
              >
                {alias.alias_normalizado}
              </li>
            ))}
            {aliasOcultos > 0 && (
              <li className="text-muted-foreground self-center text-xs">+{formatNumber(aliasOcultos)} más</li>
            )}
          </ul>
        </div>
      )}

      <Relacionadas titulo="Miembros de la UTE" empresas={empresa.ute_miembros} />
      <Relacionadas titulo="Participa en UTEs" empresas={empresa.participa_en_utes} />

      <Link
        href={`/empresas?q=${encodeURIComponent(empresa.nif_canonico ?? empresa.nombre_canonico)}`}
        className="text-primary inline-flex text-sm font-medium hover:underline"
      >
        Ver en el maestro
      </Link>
    </section>
  );
}

/** Empresas enlazadas por una UTE, cada una hacia su propia ficha. */
function Relacionadas({ titulo, empresas }: { titulo: string; empresas: Schemas["EmpresaRef"][] }) {
  if (!empresas.length) return null;
  return (
    <div>
      <h4 className="text-muted-foreground mb-2 text-xs font-semibold tracking-[0.12em] uppercase">{titulo}</h4>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-sm">
        {empresas.map((relacionada) => (
          <li key={relacionada.empresa_id}>
            <Link href={`/competencia/empresa/${relacionada.empresa_id}`} className="text-primary hover:underline">
              {relacionada.nombre_canonico}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
