"use client";

import dynamic from "next/dynamic";
import { PanelError } from "@/components/console/panel";
import { pasaFiltroEtiqueta } from "@/components/etiquetas/filtro-etiqueta";
import { useEtiquetasDe } from "@/hooks/use-etiquetas";
import { usePursuitMetrics, usePursuits } from "@/hooks/use-pursuits";
import type { Pursuit } from "@/hooks/use-pursuits";
/**
 * El diálogo de cierre, sólo cuando se cierra algo.
 *
 * Trae el `Dialog` y el `Select` de Radix, y se abre en una de cada muchas
 * visitas al tablero: estáticamente son 68 KB de First Load que paga todo el
 * mundo por un caso raro, y el presupuesto por ruta
 * (`scripts/check_bundle_budget.py`) lo cobra. Va montado bajo condición, no
 * sólo importado así: un `dynamic` que se renderiza siempre carga igual.
 */
const DialogoCierre = dynamic(
  () => import("./dialogo-cierre").then((modulo) => modulo.DialogoCierre),
  { ssr: false },
);
import { TableroColumna } from "./tablero-columna";
import { TableroMetricas } from "./tablero-metricas";
import { TableroVacio } from "./tablero-vacio";
import { useTablero } from "../_hooks/use-tablero";
import { FASES, faseDe } from "../_lib/fases";
import { bloqueoDeFase, resultadosPermitidos } from "../_lib/flujo";

/**
 * Tablero — la vista de entrada de Oportunidades, una columna por fase.
 *
 * Hasta 2026-09-20 era el cuerpo entero de `oportunidades/page.tsx`. Con la
 * reestructura («un espacio, una pregunta») la página conmuta entre tablero,
 * cartera y rendimiento, y este componente sólo se monta cuando el tablero es
 * la vista activa: así sus consultas (`usePursuits`, `usePursuitMetrics`, las
 * etiquetas de todas las tarjetas) no se disparan para mirar la cartera. Los
 * filtros (búsqueda y etiqueta) llegan como props porque sus controles viven
 * en la cabecera del espacio, que es de la página. Nada más cambió: el
 * tablero es el mismo, columna a columna.
 *
 * Una columna por estado abierto del workflow y una sola para los tres
 * terminales. La versión anterior agrupaba los ocho estados en cuatro carriles,
 * y eso escondía lo único que un tablero tiene que decir: en qué punto exacto
 * está cada oportunidad. Con una columna por fase, mover una tarjeta significa
 * algo concreto y es un PATCH de un campo (`status`, con `expected_version`).
 *
 * Arrastrar no es la única forma de mover: cada tarjeta lleva su menú «Mover
 * a», que es la vía de teclado y de lector de pantalla. Soltar en «Cerradas»
 * abre el diálogo de resultado y motivo en vez de elegir uno por el usuario.
 * Las dos vías respetan el flujo del backend (`_lib/flujo.ts`): mientras se
 * arrastra, solo aceptan la tarjeta la fase siguiente, «Cerradas» y la suya.
 *
 * La unidad sigue siendo la **oportunidad**, no el expediente: un expediente
 * dividido en lotes puede tener una por lote, así que las columnas agrupan por
 * expediente y la tira declara su unidad de conteo.
 */
export default function TableroView({
  query,
  etiquetaFiltro,
}: {
  query: string;
  etiquetaFiltro: string;
}) {
  const pursuits = usePursuits();
  const metrics = usePursuitMetrics();
  const tablero = useTablero();

  // F1.6 — una sola petición con las etiquetas de todas las tarjetas.
  const ids = (pursuits.data?.items ?? []).map((pursuit) => String(pursuit.id));
  const etiquetasPorId = useEtiquetasDe("oportunidad", ids).data ?? {};
  const items = (pursuits.data?.items ?? []).filter(
    (pursuit) =>
      coincide(pursuit, query) &&
      pasaFiltroEtiqueta(etiquetasPorId[String(pursuit.id)], etiquetaFiltro),
  );

  const vacio = !pursuits.isPending && !pursuits.error && (pursuits.data?.items?.length ?? 0) === 0;
  const arrastrada = items.find((item) => item.id === tablero.arrastrandoId) ?? null;

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <TableroMetricas metrics={metrics.data} cargando={metrics.isPending} />

        {pursuits.error ? (
          <div className="grid flex-1 place-items-center p-10">
            <PanelError
              title="No se pudieron cargar las oportunidades"
              detail={(pursuits.error as Error).message}
              onRetry={() => void pursuits.refetch()}
            />
          </div>
        ) : vacio ? (
          <TableroVacio />
        ) : (
          <div className="bg-border/50 grid min-h-0 flex-1 grid-cols-1 gap-px md:grid-cols-3 xl:grid-cols-6">
            {FASES.map((fase) => (
              <TableroColumna
                key={fase.key}
                fase={fase}
                items={items.filter((item) => faseDe(tablero.estadoDe(item)) === fase.key)}
                etiquetasPorId={etiquetasPorId}
                cargando={pursuits.isPending}
                activa={tablero.columnaActiva === fase.key}
                aceptaSoltar={arrastrada == null || bloqueoDeFase(arrastrada, fase.key) === null}
                arrastrandoId={tablero.arrastrandoId}
                onSobrevolar={() => tablero.sobrevolar(fase.key)}
                onSalir={() => tablero.salirDe(fase.key)}
                onSoltarEnColumna={() => {
                  if (arrastrada) tablero.moverA(arrastrada, fase.key);
                }}
                onArrastrar={tablero.empezarArrastre}
                onFinArrastre={tablero.terminarArrastre}
                onMover={tablero.moverA}
              />
            ))}
          </div>
        )}
      </div>

      {/* `key` por oportunidad: el diálogo se remonta limpio para cada tarjeta,
          que es cómo se reinicia su estado sin un efecto que lo haga a mano. */}
      {tablero.cierre ? (
        <DialogoCierre
          key={tablero.cierre.id}
          pursuit={tablero.cierre}
          resultados={resultadosPermitidos(tablero.cierre)}
          onCancelar={tablero.cancelarCierre}
          onConfirmar={tablero.confirmarCierre}
        />
      ) : null}
    </>
  );
}

/** Busca por título, referencia y responsable, que es lo que promete el campo. */
function coincide(pursuit: Pursuit, query: string): boolean {
  const aguja = query.trim().toLocaleLowerCase("es");
  if (!aguja) return true;
  return `${pursuit.tender_title ?? ""} ${pursuit.licitacion_id} ${pursuit.responsible_name ?? ""}`
    .toLocaleLowerCase("es")
    .includes(aguja);
}
