/**
 * axe sobre la bandeja del Radar, en jsdom (C7.1).
 *
 * Por qué existe: la regla `nested-interactive` se retiró de `disableRules`
 * porque la fila dejó de ser un `role="button"` con botones dentro, pero quien
 * lo comprobaba era `frontend-e2e`, que necesita la aplicación levantada con
 * Postgres sembrado. Un arreglo cuya única prueba vive en un job que no se puede
 * correr en local se revierte sin que nadie se entere hasta el siguiente PR.
 *
 * Qué puede y qué no puede comprobar aquí. jsdom **no calcula layout**, así que
 * axe no puede evaluar `color-contrast`, `target-size` ni
 * `scrollable-region-focusable`: sin cajas ni colores computados las declara
 * `incomplete`, no `passed`. Las estructurales —roles anidados, hijos
 * requeridos, padres requeridos— sí son puro árbol y se evalúan igual que en un
 * navegador. Este fichero se limita a esas, a propósito: un test que dijera
 * «axe pasa» sobre reglas que en realidad no se ejecutaron sería exactamente el
 * gate que miente que el resto del repo evita.
 *
 * El E2E sigue siendo el que manda. Esto es el guardarraíl barato de al lado.
 */
import * as React from "react";
import { render } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it } from "vitest";
import { RadarFila } from "@/app/(dashboard)/radar/_components/radar-fila";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { RadarTender } from "@/hooks/use-radar";

/** Reglas que jsdom sí puede evaluar: estructura del árbol, no pintura. */
const REGLAS_ESTRUCTURALES = [
  "nested-interactive",
  "aria-required-children",
  "aria-required-parent",
  "aria-allowed-role",
  "aria-allowed-attr",
];

function tender(id: string, titulo: string): RadarTender {
  return {
    id_externo: id,
    titulo,
    organo_contratacion: "Ministerio de Hacienda",
    ccaa: "Madrid",
    cpv: "72000000",
    importe: 120_000,
    fecha_limite: "2026-10-01",
    fecha_publicacion: "2026-09-01",
    score: 82,
    band: "alta",
    tecnologia: "SAP",
  } as unknown as RadarTender;
}

/** La bandeja mínima con estructura de rejilla: cabecera implícita y dos filas. */
function Bandeja() {
  const filas = [tender("LIC-1", "Fila uno"), tender("LIC-2", "Fila dos")];
  return (
    // `TooltipProvider`: las acciones de la fila usan `Tooltip`, y en la
    // aplicación lo monta `components/providers`. Envuelve por fuera de la
    // rejilla para no meter un elemento extra entre `grid` y sus filas.
    <TooltipProvider>
      <div role="grid" aria-label="Señales del Radar" aria-rowcount={filas.length + 1}>
        <div role="row" aria-rowindex={1}>
          <span role="columnheader">Score</span>
          <span role="columnheader">Licitación</span>
          <span role="columnheader">Órgano</span>
          <span role="columnheader">Tecnología</span>
          <span role="columnheader">Importe</span>
          <span role="columnheader">Plazo</span>
          <span role="columnheader">Acción</span>
        </div>
        <div role="rowgroup">
          {filas.map((fila, index) => (
            <RadarFila
              key={fila.id_externo}
              tender={fila}
              index={index}
              isActive={index === 0}
              isFollowed={false}
              isNew={false}
              rowHeight={56}
              enTabla={false}
              conFicha={false}
              onSelect={() => {}}
              onDismiss={() => {}}
              onFollow={() => {}}
              onOpenPursuit={() => {}}
              onOpenFicha={() => {}}
            />
          ))}
        </div>
      </div>
    </TooltipProvider>
  );
}

describe("axe sobre la bandeja del Radar", () => {
  it("no anida controles dentro de un rol interactivo", async () => {
    const { container } = render(<Bandeja />);

    const resultado = await axe.run(container, {
      runOnly: { type: "rule", values: REGLAS_ESTRUCTURALES },
      // El `iframe` de axe no existe aquí y su ausencia no es un hallazgo.
      iframes: false,
    });

    const violaciones = resultado.violations.map((v) => ({
      id: v.id,
      nodos: v.nodes.map((n) => n.html.slice(0, 120)),
    }));
    expect(violaciones).toEqual([]);
  });

  it("la regla que este arreglo cierra se evaluó de verdad", async () => {
    // Sin esto, el test de arriba pasaría igual si axe hubiera decidido saltarse
    // `nested-interactive` —por ejemplo si un cambio de versión la renombra—, y
    // un cero de violaciones sobre cero reglas ejecutadas no dice nada.
    const { container } = render(<Bandeja />);

    const resultado = await axe.run(container, {
      runOnly: { type: "rule", values: ["nested-interactive"] },
      iframes: false,
    });

    const evaluadas = [...resultado.passes, ...resultado.violations, ...resultado.incomplete].map((r) => r.id);
    expect(evaluadas).toContain("nested-interactive");
  });
});
