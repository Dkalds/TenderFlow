/**
 * F4.1 en Dirección: cuándo entra el dinero del pipeline abierto.
 *
 * El backend ya calculaba la previsión por trimestre para el cuadro y la tiraba;
 * ahora viaja en `prevision_trimestral`, con los supuestos con los que se
 * ponderó (`probabilidades_etapa_usadas`). La cifra total está en la tarjeta de
 * arriba; aquí va su reparto. Es una foto de hoy: no cambia con el periodo.
 */
import { Panel, PanelTitle } from "@/components/console/panel";
import { PrevisionTrimestral, SupuestosEtapas } from "@/components/pursuits/prevision-trimestral";
import type { Schemas } from "@/lib/api-types";
import { previsionOrdenada, supuestosEtapas } from "@/lib/pipeline-ponderado";
import { formatNumber } from "@/lib/utils";

type Cuadro = Schemas["CuadroDireccion"];

export function PrevisionDireccion({ cuadro }: { cuadro: Cuadro }) {
  const sinImporte = cuadro.pipeline_sin_importe ?? 0;
  return (
    <Panel>
      <PanelTitle as="h2" title="Lo que viene" hint="Valor ponderado por trimestre, foto de hoy" />
      <p className="text-tf-micro leading-normal text-muted-foreground">
        Importe de cada oportunidad abierta por la probabilidad de su etapa. Es un supuesto, no una previsión
        de cobro.
        {sinImporte > 0 ? ` ${formatNumber(sinImporte)} sin importe publicado no cuentan.` : null}
      </p>
      <SupuestosEtapas className="mt-3" supuestos={supuestosEtapas(cuadro)} />
      <PrevisionTrimestral prevision={previsionOrdenada(cuadro)} />
    </Panel>
  );
}
