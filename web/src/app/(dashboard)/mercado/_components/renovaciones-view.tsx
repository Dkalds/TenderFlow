"use client";

/**
 * Renovaciones — contratos que vencen a 3-24 meses, con el CTA de anticipar.
 *
 * Vista `?vista=renovaciones` de Mercado. La pregunta que responde es de
 * mercado y no un compromiso personal: **qué contratos vencen, sean de quien
 * sean**, cuánto valen y qué probabilidad hay de que su adjudicatario los
 * pierda. Por eso el dataset no se recorta a tu organización y por eso vive
 * junto a Tiempo, Geografía u Órganos y no en la Agenda — mirar el mercado no
 * es tener trabajo pendiente.
 *
 * Lo tuyo se trabaja en otro sitio, y el reparto importa: los contratos que
 * ganaste están en `Oportunidades → Cartera`, con su ventana de relicitación y
 * el botón de preparar la renovación, y sus plazos aparecen en la Agenda
 * (`/mi-pipeline`) cuando llega el momento de hacer algo. Aquí sólo se marcan
 * («En tu cartera», «Anticipada») para que no haya que abrir otra pantalla
 * para saber cuáles ya son tuyos.
 *
 * Hasta 2026-09-20 era «Horizonte» de Mi Pipeline. El cuerpo no está en un
 * `(dashboard)/renovaciones/page.tsx` porque `/renovaciones` redirige 308 a
 * `/mercado?vista=renovaciones` y los redirects de Next corren antes que el
 * enrutado por sistema de ficheros: ese `page.tsx` no se ejecutaría nunca.
 * Mismo reparto que el resto de vistas de este espacio. Los enlaces guardados
 * los preserva el 308; los `?vista=horizonte` y `?vista=renovaciones` viejos de
 * `/mi-pipeline` los reenvía aquella página.
 *
 * Datos, corte y acciones viven en `_hooks/use-renovaciones.ts`; las piezas de
 * pantalla, en `_components/renovaciones/`. Aquí queda el reparto de la
 * pantalla, el selector de ventana y el error, que es el único estado que
 * sustituye a todo lo demás. La banda `PipelineRoleNav` que orientaba entre
 * agenda, horizonte y calendario se retiró: el conmutador de vistas del
 * espacio ya hace ese trabajo.
 */

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PanelError } from "@/components/console/panel";
import { HORIZONTES, useRenovaciones } from "../_hooks/use-renovaciones";
import { RenovacionesCartera } from "./renovaciones/renovaciones-cartera";
import { RenovacionesKpis } from "./renovaciones/renovaciones-kpis";
import { RenovacionesLista } from "./renovaciones/renovaciones-lista";

export default function RenovacionesView() {
  const renovaciones = useRenovaciones();

  if (renovaciones.error) {
    return (
      <PanelError
        title="No se pudieron cargar las renovaciones"
        detail={(renovaciones.error as Error).message}
        onRetry={renovaciones.recargar}
        height={320}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-[70ch] text-[11.5px] leading-[1.5] text-muted-foreground">
          Contratos adjudicados que vencen pronto: o los defiende el adjudicatario actual o se los disputa
          quien llegue primero. Los tuyos se preparan desde Oportunidades → Cartera.
        </p>
        <Select value={renovaciones.meses} onValueChange={renovaciones.setMeses}>
          <SelectTrigger className="h-7 w-[132px] flex-none text-xs" aria-label="Horizonte de vencimiento">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {HORIZONTES.map((h) => (
              <SelectItem key={h.value} value={h.value}>
                {h.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <RenovacionesKpis totales={renovaciones.totales} />

      <RenovacionesCartera
        meses={renovaciones.meses}
        topCartera={renovaciones.topCartera}
        isLoading={renovaciones.isLoading}
      />

      <RenovacionesLista
        items={renovaciones.items}
        isLoading={renovaciones.isLoading}
        empresaSearch={renovaciones.empresaSearch}
        onEmpresaSearchChange={renovaciones.setEmpresaSearch}
        maxScore={renovaciones.maxScore}
        onAnticipar={(licitacionId) => void renovaciones.anticipar(licitacionId)}
        onAbrirDetalle={renovaciones.abrirDetalle}
      />
    </div>
  );
}
