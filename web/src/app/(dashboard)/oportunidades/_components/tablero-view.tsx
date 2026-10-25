"use client";

import dynamic from "next/dynamic";
import { Aviso, PanelEmpty, PanelError } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { useDebounce } from "@/hooks/use-debounce";
import { useEtiquetasDe } from "@/hooks/use-etiquetas";
import { usePursuitMetrics, usePursuits } from "@/hooks/use-pursuits";
import { formatNumber } from "@/lib/utils";
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
import { consultaDelTablero, hayFiltros, type FiltrosTablero } from "../_lib/filtros-tablero";
import { bloqueoDeFase, resultadosPermitidos } from "../_lib/flujo";

/**
 * Tablero — la vista de entrada de Oportunidades, una columna por fase.
 *
 * Hasta 2026-09-20 era el cuerpo entero de `oportunidades/page.tsx`. Con la
 * reestructura («un espacio, una pregunta») la página conmuta entre tablero,
 * cartera y rendimiento, y este componente sólo se monta cuando el tablero es
 * la vista activa: así sus consultas (`usePursuits`, `usePursuitMetrics`, las
 * etiquetas de todas las tarjetas) no se disparan para mirar la cartera. Los
 * filtros llegan como props porque sus controles viven en la cabecera del
 * espacio, que es de la página.
 *
 * Los filtros se aplican **en servidor** (CU-28): el tablero pide hasta
 * `TOPE_TABLERO` oportunidades ya filtradas y el `total` de la respuesta es el
 * del conjunto filtrado. Antes pedía la página por defecto y filtraba en el
 * navegador, así que lo que no cabía en ella no aparecía por mucho que se
 * buscara. Si el conjunto supera el tope, el tablero lo dice.
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
 * Las dos vías respetan el flujo de estados (`_lib/flujo.ts`): mientras se
 * arrastra, solo aceptan la tarjeta la fase siguiente, «Cerradas» y la suya.
 *
 * La unidad sigue siendo la **oportunidad**, no el expediente: un expediente
 * dividido en lotes puede tener una por lote, así que las columnas agrupan por
 * expediente y la tira declara su unidad de conteo.
 */
export default function TableroView({
  filtros,
  onLimpiar,
}: {
  filtros: FiltrosTablero;
  onLimpiar: () => void;
}) {
  // El texto espera a que se deje de escribir: cada tecla sería una consulta.
  const q = useDebounce(filtros.q, 300);
  const conFiltros = hayFiltros(filtros);
  const pursuits = usePursuits(consultaDelTablero({ ...filtros, q }));
  const metrics = usePursuitMetrics();
  const tablero = useTablero();

  // F1.6 — una sola petición con las etiquetas de todas las tarjetas.
  const items = pursuits.data?.items ?? [];
  const ids = items.map((pursuit) => String(pursuit.id));
  const etiquetasPorId = useEtiquetasDe("oportunidad", ids).data ?? {};

  const sinResultados = !pursuits.isPending && !pursuits.error && items.length === 0;
  const total = pursuits.data?.total ?? 0;
  const arrastrada = items.find((item) => item.id === tablero.arrastrandoId) ?? null;

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <TableroMetricas metrics={metrics.data} cargando={metrics.isPending} />

        {pursuits.error ? (
          <div className="grid flex-1 place-items-center p-10">
            <PanelError
              title="No se pudieron cargar las oportunidades"
              error={pursuits.error}
              onRetry={() => void pursuits.refetch()}
            />
          </div>
        ) : sinResultados && conFiltros ? (
          <div className="grid flex-1 place-items-center p-10">
            <PanelEmpty
              title="Ninguna oportunidad con estos filtros"
              hint="Prueba con otro plazo, otra etiqueta u otro responsable, o quita los filtros."
              action={
                <Button type="button" size="sm" variant="outline" onClick={onLimpiar}>
                  Quitar filtros
                </Button>
              }
            />
          </div>
        ) : sinResultados ? (
          <TableroVacio />
        ) : (
          <>
            <AvisoDelTablero
              filtros={filtros}
              total={total}
              cargadas={items.length}
              cargando={pursuits.isPending}
            />
            <div className="bg-divider grid min-h-0 flex-1 grid-cols-1 gap-px md:grid-cols-3 xl:grid-cols-6">
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
          </>
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

/**
 * Lo que el tablero tiene que decir de su universo (ADR-014): cuántas casan con
 * los filtros, que la tira de arriba sigue siendo de toda la organización, qué
 * cuenta el plazo y si lo que se ve es parcial. Sin filtros y sin recorte, nada.
 */
function AvisoDelTablero({
  filtros,
  total,
  cargadas,
  cargando,
}: {
  filtros: FiltrosTablero;
  total: number;
  cargadas: number;
  cargando: boolean;
}) {
  if (cargando) return null;
  const parcial = total > cargadas;
  if (!hayFiltros(filtros) && !parcial) return null;
  return (
    <Aviso tone={parcial ? "warning" : "info"} variant="banda" className="flex-none">
      {hayFiltros(filtros)
        ? `${formatNumber(total)} ${total === 1 ? "oportunidad casa" : "oportunidades casan"} con los filtros; la tira de arriba es de toda la organización.`
        : `Hay ${formatNumber(total)} oportunidades.`}
      {filtros.plazo !== "todos" && " El plazo solo cuenta las abiertas sin presentar."}
      {parcial && ` Se ven las ${formatNumber(cargadas)} con actividad más reciente: acota con los filtros para ver el resto.`}
    </Aviso>
  );
}
