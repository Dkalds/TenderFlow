"use client";

/**
 * La red de alianzas: cada empresa es un nodo y cada línea une a dos que han
 * firmado una UTE juntas; el grosor dice cuántas.
 *
 * El dibujo es para la vista y el ratón, y va oculto al lector de pantalla: los
 * mismos pares, con sus UTE y su importe, están en la lista de al lado
 * (`utes-alianzas.tsx`), que es la que se recorre con el teclado. Por eso los
 * nodos responden al clic pero no son paradas de tabulación.
 *
 * Todos los nodos miden lo mismo: la API da cifras por par, no por empresa, y
 * sumarlas aquí sería contar sólo los pares que llegan. Dónde va cada uno lo
 * decide `_hooks/utes-red.ts`.
 */

import { Panel, PanelEmpty, PanelLoading, PanelTitle } from "@/components/console/panel";
import { CHART_SERIES } from "@/lib/chart-colors";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";

import { RED_ALTO, RED_ANCHO, type RedMarcada } from "../_hooks/utes-red";

const PRIMARIO = "hsl(var(--primary))";
const COLOR_LINEA = CHART_SERIES[1];

/** Opacidad de una línea según lo que le toque de la selección. */
const OPACIDAD_LINEA = { normal: 0.6, resaltada: 0.9, atenuada: 0.14 } as const;

type Nodo = RedMarcada["nodos"][number];
type Arista = RedMarcada["aristas"][number];

function Linea({ arista }: { arista: Arista }) {
  return (
    <line
      x1={arista.x1}
      y1={arista.y1}
      x2={arista.x2}
      y2={arista.y2}
      stroke={arista.estado === "resaltada" ? PRIMARIO : COLOR_LINEA}
      strokeWidth={arista.grosor}
      strokeOpacity={OPACIDAD_LINEA[arista.estado]}
      strokeLinecap="round"
    >
      <title>
        {`${arista.a} y ${arista.b}: ${formatNumber(arista.contratos)} UTE juntas, ${formatCurrency(arista.importe)}`}
      </title>
    </line>
  );
}

/** El número de UTE de una alianza de la empresa elegida, a mitad de su línea. */
function Pastilla({ arista }: { arista: Arista }) {
  const cifra = formatNumber(arista.contratos);
  const ancho = 12 + cifra.length * 7;
  return (
    <g>
      <rect
        x={arista.medioX - ancho / 2}
        y={arista.medioY - 8}
        width={ancho}
        height="16"
        rx="8"
        className="fill-card"
        stroke={PRIMARIO}
        strokeOpacity="0.3"
      />
      <text
        x={arista.medioX}
        y={arista.medioY}
        textAnchor="middle"
        dominantBaseline="central"
        className="tf-tnum text-tf-micro font-bold"
        fill={PRIMARIO}
      >
        {cifra}
      </text>
    </g>
  );
}

function NodoEmpresa({ nodo, onElegir }: { nodo: Nodo; onElegir: (empresa: string) => void }) {
  const elegido = nodo.estado === "elegido";
  return (
    <g
      data-nodo={nodo.nombre}
      data-estado={nodo.estado}
      className="cursor-pointer"
      opacity={nodo.estado === "atenuado" ? 0.35 : 1}
      onClick={() => onElegir(nodo.nombre)}
    >
      <title>{nodo.nombre}</title>
      {/* Diana del clic, más ancha que el punto. */}
      <circle cx={nodo.x} cy={nodo.y} r="13" fill="transparent" />
      {elegido && <circle cx={nodo.x} cy={nodo.y} r="11" fill="none" stroke={PRIMARIO} strokeWidth="2" />}
      <circle
        cx={nodo.x}
        cy={nodo.y}
        r={elegido ? 7.5 : 6.5}
        fill={elegido ? PRIMARIO : undefined}
        className={cn("stroke-card", !elegido && "fill-foreground")}
        strokeWidth="2"
      />
      <text
        x={nodo.etiquetaX}
        y={nodo.y}
        textAnchor={nodo.ancla}
        dominantBaseline="central"
        fill={elegido ? PRIMARIO : undefined}
        className={cn("text-tf-meta", elegido ? "font-bold" : "fill-foreground font-medium")}
      >
        {nodo.etiqueta}
      </text>
    </g>
  );
}

function Leyenda() {
  return (
    <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-tf-micro text-muted-foreground">
      <li className="flex items-center gap-1.5">
        <svg aria-hidden="true" className="h-2.5 w-11 flex-none" viewBox="0 0 44 10">
          <line x1="1" y1="5" x2="18" y2="5" stroke={COLOR_LINEA} strokeWidth="2" strokeLinecap="round" />
          <line x1="28" y1="5" x2="40" y2="5" stroke={COLOR_LINEA} strokeWidth="8" strokeLinecap="round" />
        </svg>
        Más gruesa, más UTE firmadas juntas
      </li>
      <li className="flex items-center gap-1.5">
        <svg aria-hidden="true" className="h-3.5 w-3.5 flex-none" viewBox="0 0 14 14">
          <circle cx="7" cy="7" r="6" fill="none" stroke={PRIMARIO} strokeWidth="1.5" />
          <circle cx="7" cy="7" r="3.5" fill={PRIMARIO} />
        </svg>
        Empresa elegida y sus alianzas
      </li>
    </ul>
  );
}

export function UtesRed({
  red,
  isLoading,
  onElegir,
}: {
  red: RedMarcada;
  isLoading: boolean;
  onElegir: (empresa: string) => void;
}) {
  const pares = red.aristas.length;
  // Las resaltadas se pintan las últimas, para que queden encima del resto.
  const resaltadas = red.aristas.filter((arista) => arista.estado === "resaltada");
  const deFondo = red.aristas.filter((arista) => arista.estado !== "resaltada");

  return (
    <Panel className="flex min-w-0 flex-col">
      <PanelTitle title="Red de alianzas" hint="cada línea une a dos empresas que han firmado una UTE juntas" />
      {isLoading ? (
        <PanelLoading height={RED_ALTO} />
      ) : pares === 0 ? (
        <PanelEmpty
          title="Ningún par de socios"
          hint="Ninguna pareja de empresas ha firmado una UTE junta en el ámbito actual."
          height={RED_ALTO}
        />
      ) : (
        <>
          <Leyenda />
          <div
            role="group"
            aria-label="Dibujo de la red de alianzas"
            // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- caja con scroll horizontal sin controles dentro: el teclado tiene que poder desplazarla (axe scrollable-region-focusable)
            tabIndex={0}
            className="relative mb-3 overflow-x-auto rounded-md"
          >
            <svg
              aria-hidden="true"
              viewBox={`0 0 ${RED_ANCHO} ${RED_ALTO}`}
              className="mx-auto block h-auto w-full min-w-[36rem] max-w-[52rem]"
            >
              {deFondo.map((arista) => (
                <Linea key={arista.clave} arista={arista} />
              ))}
              {resaltadas.map((arista) => (
                <Linea key={arista.clave} arista={arista} />
              ))}
              {resaltadas.map((arista) => (
                <Pastilla key={arista.clave} arista={arista} />
              ))}
              {red.nodos.map((nodo) => (
                <NodoEmpresa key={nodo.nombre} nodo={nodo} onElegir={onElegir} />
              ))}
            </svg>
          </div>
          <p className="mt-auto border-t border-border/60 pt-2.5 text-tf-meta text-muted-foreground">
            {pares === 1
              ? "El par con más UTE del ámbito. "
              : `Los ${formatNumber(pares)} pares con más UTE del ámbito, no todos. `}
            Son empresas que licitaron juntas de verdad, no que coinciden en una zona.
          </p>
        </>
      )}
    </Panel>
  );
}
