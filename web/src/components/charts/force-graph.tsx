"use client";

import * as React from "react";
import { select } from "d3-selection";
import { max } from "d3-array";
import { scaleSqrt, scaleOrdinal, scaleLinear } from "d3-scale";
import { schemeTableau10 } from "d3-scale-chromatic";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  forceX,
  forceY,
} from "d3-force";
import type { SimulationNodeDatum, SimulationLinkDatum } from "d3-force";
import { zoom as d3Zoom, zoomIdentity, type ZoomBehavior } from "d3-zoom";
import { drag as d3Drag } from "d3-drag";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Public types                                                      */
/* ------------------------------------------------------------------ */

export interface GraphNode {
  id: string;
  label: string;
  /** Color key — tipo de nodo ("organo"/"empresa") o comunidad ("c0"…). */
  group: string;
  size?: number;
  /** Métricas opcionales para el tooltip. */
  importe?: number;
  contratos?: number;
  degree?: number;
  /** Columna en layout bipartito (0 = izquierda, 1 = derecha). */
  column?: 0 | 1;
}

export interface GraphLink {
  source: string;
  target: string;
  weight?: number;
  importe?: number;
  contratos?: number;
}

export interface ForceGraphProps {
  nodes: GraphNode[];
  links: GraphLink[];
  height?: number;
  className?: string;
  /** "force" (libre, con contención) o "bipartite" (dos columnas por `column`). */
  layout?: "force" | "bipartite";
  /** Ids a resaltar (p.ej. resultados de búsqueda). */
  highlightIds?: string[];
  /** Etiqueta legible por grupo para la leyenda (group → texto). */
  groupLabels?: Record<string, string>;
  showLegend?: boolean;
  onNodeClick?: (id: string) => void;
  onLinkClick?: (source: string, target: string) => void;
}

/* ------------------------------------------------------------------ */
/*  Internal sim types                                                */
/* ------------------------------------------------------------------ */

interface SimNode extends SimulationNodeDatum {
  id: string;
  label: string;
  group: string;
  radius: number;
  column?: 0 | 1;
  importe?: number;
  contratos?: number;
  degree?: number;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  weight: number;
  importe?: number;
  contratos?: number;
}

interface TooltipState {
  x: number;
  y: number;
  html: React.ReactNode;
}

/* Virtual coordinate space — the SVG `viewBox` scales it to the container, so
   resizing never re-runs the simulation (root cause of the old "explode on
   resize" bug). */
const VW = 1000;

export const ForceGraph = React.memo(function ForceGraph({
  nodes,
  links,
  height = 420,
  className,
  layout = "force",
  highlightIds,
  groupLabels,
  showLegend = true,
  onNodeClick,
  onLinkClick,
}: ForceGraphProps) {
  const VH = height;

  const prefersReducedMotion =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const svgRef = React.useRef<SVGSVGElement>(null);
  const zoomRef = React.useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const adjacencyRef = React.useRef<Map<string, Set<string>>>(new Map());
  const [tooltip, setTooltip] = React.useState<TooltipState | null>(null);
  // Ref para que los handlers d3 (closure estable) lleguen al setter actual.
  const setTooltipRef = React.useRef(setTooltip);
  setTooltipRef.current = setTooltip;
  const onNodeClickRef = React.useRef(onNodeClick);
  onNodeClickRef.current = onNodeClick;
  const onLinkClickRef = React.useRef(onLinkClick);
  onLinkClickRef.current = onLinkClick;

  // Escala de color por grupo — única fuente de verdad (la leyenda usa la misma).
  const groups = React.useMemo(
    () => Array.from(new Set(nodes.map((n) => n.group))).sort(),
    [nodes],
  );
  const colorOf = React.useMemo(() => {
    const scale = scaleOrdinal<string, string>(schemeTableau10).domain(groups);
    return (g: string) => scale(g);
  }, [groups]);

  /* ── Build simulation + DOM (deps: data/layout/size, NOT container width) ── */
  React.useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const svg = select(svgEl);
    svg.selectAll("*").remove();
    if (nodes.length === 0) return;

    const sizeValues = nodes.map((n) => n.size ?? 8);
    const sizeScale = scaleSqrt()
      .domain([0, max(sizeValues) ?? 8])
      .range([5, 26]);

    const weights = links.map((l) => l.weight ?? 1);
    const widthScale = scaleLinear()
      .domain([1, max(weights) ?? 1])
      .range([1, 6]);

    const simNodes: SimNode[] = nodes.map((n) => ({
      id: n.id,
      label: n.label,
      group: n.group,
      column: n.column,
      importe: n.importe,
      contratos: n.contratos,
      degree: n.degree,
      radius: sizeScale(n.size ?? 8),
    }));

    const simLinks: SimLink[] = links.map((l) => ({
      source: l.source,
      target: l.target,
      weight: l.weight ?? 1,
      importe: l.importe,
      contratos: l.contratos,
    }));

    // Adyacencia para el resaltado de vecindario.
    const adjacency = new Map<string, Set<string>>();
    for (const n of simNodes) adjacency.set(n.id, new Set());
    for (const l of simLinks) {
      adjacency.get(l.source as string)?.add(l.target as string);
      adjacency.get(l.target as string)?.add(l.source as string);
    }
    adjacencyRef.current = adjacency;

    const linkForce = forceLink<SimNode, SimLink>(simLinks)
      .id((d) => d.id)
      // Relaciones más fuertes → nodos más cerca.
      .distance((d) => 120 / Math.sqrt((d.weight ?? 1) + 1))
      .strength((d) => Math.min(1, 0.15 + (d.weight ?? 1) * 0.05));

    const charge = forceManyBody<SimNode>().strength(
      layout === "bipartite" ? -180 : -220,
    );

    const simulation = forceSimulation(simNodes)
      .force("link", linkForce)
      .force("charge", charge)
      .force("collide", forceCollide<SimNode>().radius((d) => d.radius + 4));

    if (layout === "bipartite") {
      simulation
        .force(
          "x",
          forceX<SimNode>((d) => (d.column === 0 ? VW * 0.28 : VW * 0.72)).strength(0.45),
        )
        .force("y", forceY<SimNode>(VH / 2).strength(0.06));
    } else {
      // Contención suave hacia el centro: los componentes inconexos no se escapan.
      simulation
        .force("center", forceCenter(VW / 2, VH / 2))
        .force("x", forceX<SimNode>(VW / 2).strength(0.05))
        .force("y", forceY<SimNode>(VH / 2).strength(0.07));
    }

    const root = svg.append("g");

    // Zoom/pan sobre el grupo raíz.
    const zoomBehavior = d3Zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 6])
      .on("zoom", (event) => root.attr("transform", event.transform.toString()));
    svg.call(zoomBehavior);
    zoomRef.current = zoomBehavior;

    const link = root
      .append("g")
      .attr("data-testid", "graph-links")
      .selectAll("line")
      .data(simLinks)
      .join("line")
      .attr("stroke", "hsl(var(--muted-foreground))")
      .attr("stroke-opacity", 0.35)
      .attr("stroke-width", (d) => widthScale(d.weight))
      .style("cursor", onLinkClickRef.current ? "pointer" : "default")
      .on("click", (_e, d) =>
        onLinkClickRef.current?.(d.source as unknown as string, d.target as unknown as string),
      );

    const node = root
      .append("g")
      .attr("data-testid", "graph-nodes")
      .selectAll<SVGCircleElement, SimNode>("circle")
      .data(simNodes)
      .join("circle")
      .attr("r", (d) => d.radius)
      .attr("fill", (d) => colorOf(d.group))
      .attr("stroke", "hsl(var(--background))")
      .attr("stroke-width", 1.5)
      .attr("data-id", (d) => d.id)
      .attr("data-group", (d) => d.group)
      .style("cursor", "pointer")
      .on("mouseenter", (event: MouseEvent, d) => {
        setHover(d.id);
        const metrics: React.ReactNode[] = [];
        if (d.importe != null)
          metrics.push(`Importe: ${formatCurrency(d.importe)}`);
        if (d.contratos != null)
          metrics.push(`Contratos: ${formatNumber(d.contratos)}`);
        if (d.degree != null) metrics.push(`Conexiones: ${formatNumber(d.degree)}`);
        setTooltipRef.current({
          x: event.offsetX + 12,
          y: event.offsetY + 12,
          html: (
            <>
              <strong>{d.label}</strong>
              {metrics.map((m, i) => (
                <div key={i}>{m}</div>
              ))}
            </>
          ),
        });
      })
      .on("mousemove", (event: MouseEvent) =>
        setTooltipRef.current((t) =>
          t ? { ...t, x: event.offsetX + 12, y: event.offsetY + 12 } : t,
        ),
      )
      .on("mouseleave", () => {
        setHover(null);
        setTooltipRef.current(null);
      })
      .on("click", (_e, d) => onNodeClickRef.current?.(d.id));

    const dragBehavior = d3Drag<SVGCircleElement, SimNode>()
      .on("start", (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });
    node.call(dragBehavior);

    // Etiquetas: top-K por tamaño (decluttered), el resto aparece en hover.
    const labelCount = Math.min(simNodes.length, layout === "bipartite" ? 24 : 14);
    const labelIds = new Set(
      [...simNodes]
        .sort((a, b) => b.radius - a.radius)
        .slice(0, labelCount)
        .map((n) => n.id),
    );
    const labels = root
      .append("g")
      .selectAll("text")
      .data(simNodes.filter((n) => labelIds.has(n.id)))
      .join("text")
      .text((d) => d.label)
      .attr("text-anchor", "middle")
      .attr("dy", (d) => -d.radius - 4)
      .attr("fill", "hsl(var(--foreground))")
      .style("font-size", "11px")
      .style("pointer-events", "none");

    const clamp = (v: number, lo: number, hi: number) =>
      Math.max(lo, Math.min(hi, v));

    const ticked = () => {
      for (const n of simNodes) {
        n.x = clamp(n.x ?? VW / 2, n.radius, VW - n.radius);
        n.y = clamp(n.y ?? VH / 2, n.radius, VH - n.radius);
      }
      link
        .attr("x1", (d) => (d.source as SimNode).x ?? 0)
        .attr("y1", (d) => (d.source as SimNode).y ?? 0)
        .attr("x2", (d) => (d.target as SimNode).x ?? 0)
        .attr("y2", (d) => (d.target as SimNode).y ?? 0);
      node.attr("cx", (d) => d.x ?? 0).attr("cy", (d) => d.y ?? 0);
      labels.attr("x", (d) => d.x ?? 0).attr("y", (d) => d.y ?? 0);
    };

    const fitToView = () => {
      const xs = simNodes.map((n) => n.x ?? VW / 2);
      const ys = simNodes.map((n) => n.y ?? VH / 2);
      const minX = Math.min(...xs) - 40;
      const maxX = Math.max(...xs) + 40;
      const minY = Math.min(...ys) - 40;
      const maxY = Math.max(...ys) + 40;
      const w = Math.max(1, maxX - minX);
      const h = Math.max(1, maxY - minY);
      svg.attr("viewBox", `${minX} ${minY} ${w} ${h}`);
    };

    if (prefersReducedMotion) {
      simulation.stop();
      for (let i = 0; i < 250; i++) simulation.tick();
      ticked();
      fitToView();
    } else {
      simulation.on("tick", ticked);
      simulation.on("end", fitToView);
      // Encuadre temprano para que no nazca descentrado.
      window.setTimeout(fitToView, 400);
    }

    return () => {
      simulation.stop();
    };
    // colorOf depende de groups (de nodes); incluido para refrescar el fill.
  }, [nodes, links, layout, VH, prefersReducedMotion, colorOf]);

  /* ── Resaltado: highlightIds (búsqueda) o hover (vecindario) ── */
  const [hoverId, setHoverId] = React.useState<string | null>(null);
  const setHover = (id: string | null) => setHoverId(id);

  React.useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const svg = select(svgEl);

    let active: Set<string> | null = null;
    if (hoverId) {
      active = new Set<string>([hoverId, ...(adjacencyRef.current.get(hoverId) ?? [])]);
    } else if (highlightIds && highlightIds.length > 0) {
      active = new Set(highlightIds);
    }

    svg
      .select('[data-testid="graph-nodes"]')
      .selectAll<SVGCircleElement, SimNode>("circle")
      .attr("opacity", (d) => (active ? (active.has(d.id) ? 1 : 0.15) : 1))
      .attr("stroke", (d) =>
        active && active.has(d.id) && (highlightIds?.includes(d.id) || d.id === hoverId)
          ? "hsl(var(--primary))"
          : "hsl(var(--background))",
      )
      .attr("stroke-width", (d) =>
        active && (highlightIds?.includes(d.id) || d.id === hoverId) && active.has(d.id)
          ? 2.5
          : 1.5,
      );

    svg
      .select('[data-testid="graph-links"]')
      .selectAll<SVGLineElement, SimLink>("line")
      .attr("stroke-opacity", (d) => {
        if (!active) return 0.35;
        const s = (d.source as SimNode).id ?? (d.source as unknown as string);
        const t = (d.target as SimNode).id ?? (d.target as unknown as string);
        return active.has(s) && active.has(t) ? 0.6 : 0.05;
      });
  }, [hoverId, highlightIds, nodes, links]);

  const handleFit = () => {
    const svgEl = svgRef.current;
    if (!svgEl || !zoomRef.current) return;
    select(svgEl).call(zoomRef.current.transform, zoomIdentity);
  };

  /* ── Legend (data-driven: misma escala que los nodos) ── */
  const legendItems = groups.map((g) => ({
    group: g,
    color: colorOf(g),
    label: groupLabels?.[g] ?? g,
  }));

  if (nodes.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Sin datos disponibles
      </p>
    );
  }

  return (
    <div className={cn("relative w-full", className)}>
      {showLegend && legendItems.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
          {legendItems.map((item) => (
            <span
              key={item.group}
              className="flex items-center gap-1.5 text-xs text-muted-foreground"
            >
              <span
                className="inline-block h-3 w-3 rounded-full"
                style={{ backgroundColor: item.color }}
              />
              {item.label}
            </span>
          ))}
          <button
            type="button"
            onClick={handleFit}
            className="ml-auto rounded border px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-muted"
          >
            Encuadrar
          </button>
        </div>
      )}
      <svg
        ref={svgRef}
        width="100%"
        height={VH}
        viewBox={`0 0 ${VW} ${VH}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Grafo de relaciones"
        style={{ touchAction: "none" }}
      >
        <title>Grafo de relaciones</title>
      </svg>
      {tooltip && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-10 rounded border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          {tooltip.html}
        </div>
      )}
    </div>
  );
});
