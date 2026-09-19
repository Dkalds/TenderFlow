"use client";

import * as React from "react";
import { PanelError } from "@/components/console/panel";
import { SpaceShell } from "@/components/layout/space-shell";
import { useEtiquetas, useEtiquetasDe, type EtiquetaAplicada } from "@/hooks/use-etiquetas";
import { usePursuitMetrics, usePursuits } from "@/hooks/use-pursuits";
import type { Pursuit } from "@/hooks/use-pursuits";
import { DialogoCierre } from "./_components/dialogo-cierre";
import { TODAS, TableroFiltros } from "./_components/tablero-filtros";
import { TableroColumna } from "./_components/tablero-columna";
import { TableroMetricas } from "./_components/tablero-metricas";
import { TableroVacio } from "./_components/tablero-vacio";
import { useTablero } from "./_hooks/use-tablero";
import { FASES, faseDe } from "./_lib/fases";
import { bloqueoDeFase, resultadosPermitidos } from "./_lib/flujo";

/**
 * Oportunidades — tablero por fases.
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
export default function OportunidadesPage() {
  const [query, setQuery] = React.useState("");
  const [etiquetaFiltro, setEtiquetaFiltro] = React.useState<string>(TODAS);
  const pursuits = usePursuits();
  const metrics = usePursuitMetrics();
  const tablero = useTablero();

  // F1.6 — una sola petición con las etiquetas de todas las tarjetas.
  const ids = (pursuits.data?.items ?? []).map((pursuit) => String(pursuit.id));
  const etiquetasPorId = useEtiquetasDe("oportunidad", ids).data ?? {};
  const etiquetasOrg = useEtiquetas().data ?? [];

  const items = (pursuits.data?.items ?? []).filter(
    (pursuit) => coincide(pursuit, query) && tieneEtiqueta(etiquetasPorId[String(pursuit.id)], etiquetaFiltro),
  );

  const filtros = (
    <TableroFiltros
      query={query}
      onQuery={setQuery}
      etiqueta={etiquetaFiltro}
      onEtiqueta={setEtiquetaFiltro}
      etiquetas={etiquetasOrg}
    />
  );

  const vacio = !pursuits.isLoading && !pursuits.error && (pursuits.data?.items?.length ?? 0) === 0;
  const arrastrada = items.find((item) => item.id === tablero.arrastrandoId) ?? null;

  return (
    <SpaceShell spaceKey="oportunidades" actions={filtros} bleed>
      <div className="flex h-full min-h-0 flex-col">
        <TableroMetricas metrics={metrics.data} cargando={metrics.isLoading} />

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
                cargando={pursuits.isLoading}
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
      <DialogoCierre
        key={tablero.cierre?.id ?? "sin-cierre"}
        pursuit={tablero.cierre}
        resultados={tablero.cierre ? resultadosPermitidos(tablero.cierre) : undefined}
        onCancelar={tablero.cancelarCierre}
        onConfirmar={tablero.confirmarCierre}
      />
    </SpaceShell>
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

/** F1.6 — ¿la tarjeta pasa el filtro de etiqueta? `TODAS` no filtra. */
function tieneEtiqueta(etiquetas: readonly EtiquetaAplicada[] | undefined, filtro: string): boolean {
  return filtro === TODAS || (etiquetas ?? []).some((etiqueta) => String(etiqueta.id) === filtro);
}
