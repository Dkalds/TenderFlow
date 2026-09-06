"use client";

/**
 * Ficha de la empresa seleccionada: identidad, totales, trayectoria por año y
 * los tres desgloses competitivos.
 */

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { CompanyYearTrend } from "@/components/competitors/company-year-trend";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";
import { useEmpresaPerfil } from "../_hooks/use-empresa-perfil";
import { EmpresaRelaciones } from "./empresa-relaciones";
import { MiniRanking } from "./mini-ranking";

/** Corte del nombre del órgano en el ranking, que suele ser larguísimo. */
const MAX_ORGANO = 38;

export function EmpresaPerfil({ empresaId }: { empresaId: number }) {
  const { detail, perfil, isLoading } = useEmpresaPerfil(empresaId);

  if (isLoading || !detail) {
    return <Skeleton className="h-[380px] w-full" />;
  }

  const totales = perfil?.totales;
  const porAnio = perfil?.por_anio ?? [];

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle>{detail.nombre_canonico}</CardTitle>
          {detail.es_ute ? <Badge variant="outline">UTE</Badge> : null}
          {detail.grupo && <Badge variant="secondary">Grupo {detail.grupo}</Badge>}
        </div>
        <CardDescription className="font-mono">
          {detail.nif_canonico ?? "Sin NIF canónico"}
          {totales?.primera_adjudicacion &&
            ` · activa de ${totales.primera_adjudicacion.slice(0, 10)} a ${totales.ultima_adjudicacion?.slice(0, 10) ?? "hoy"}`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Totales */}
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-xs font-medium uppercase text-muted-foreground">Contratos</p>
            <p className="font-mono text-xl font-bold">{formatNumber(totales?.contratos ?? 0)}</p>
          </div>
          <div>
            <p className="text-xs font-medium uppercase text-muted-foreground">
              Importe adjudicado
            </p>
            <p className="font-mono text-xl font-bold">
              {valorOEmpty(totales?.importe_total, formatCurrency)}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium uppercase text-muted-foreground">
              Ofertas medias (presión)
            </p>
            <p className="font-mono text-xl font-bold">{totales?.ofertas_medias ?? "—"}</p>
          </div>
        </div>

        <Separator />

        {/* Trayectoria temporal: ¿crece o decae? (señal competitiva) */}
        {porAnio.length > 0 && (
          <>
            <CompanyYearTrend rows={porAnio} />
            <Separator />
          </>
        )}

        {/* Desgloses */}
        <div className="grid gap-6 lg:grid-cols-3">
          <MiniRanking
            title="Por familia CPV"
            rows={(perfil?.por_cpv ?? []).map((r) => ({
              label: `CPV ${r.cpv2}`,
              contratos: r.contratos,
              importe: r.importe,
            }))}
          />
          <MiniRanking
            title="Por territorio"
            rows={(perfil?.por_ccaa ?? []).map((r) => ({
              label: r.ccaa,
              contratos: r.contratos,
              importe: r.importe,
            }))}
          />
          <MiniRanking
            title="Órganos principales"
            rows={(perfil?.organos_principales ?? []).map((r) => ({
              label: truncate(r.organo, MAX_ORGANO),
              contratos: r.contratos,
              importe: r.importe,
            }))}
          />
        </div>

        {/* UTEs y aliases */}
        <EmpresaRelaciones detail={detail} />
      </CardContent>
    </Card>
  );
}
