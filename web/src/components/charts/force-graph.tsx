"use client";

import * as React from "react";
import { select } from "d3-selection";
import { median, max } from "d3-array";
import { scaleSqrt, scaleOrdinal } from "d3-scale";
import { schemeTableau10 } from "d3-scale-chromatic";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from "d3-force";
import type { SimulationNodeDatum, SimulationLinkDatum } from "d3-force";
import { zoom as d3Zoom } from "d3-zoom";
import { drag as d3Drag } from "d3-drag";
import { cn } from "@/lib/utils";

interface GraphNode {
  id: string;
  label: string;
  group: string;
  size?: number;
}

interface GraphLink {
  source: string;
  target: string;
  weight?: number;
}

interface ForceGraphProps {
  nodes: GraphNode[];
  links: GraphLink[];
  width?: number;
  height?: number;
  className?: string;
  onNodeClick?: (nodeId: string) => void;
}

interface SimNode extends SimulationNodeDatum {
  id: string;
  label: string;
  group: string;
  radius: number;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  weight: number;
}

export const ForceGraph = React.memo(function ForceGraph({
  nodes,
  links,
  width: propWidth,
  height: propHeight,
  className,
  onNodeClick,
}: ForceGraphProps) {
  const prefersReducedMotion = typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const containerRef = React.useRef<HTMLDivElement>(null);
  const svgRef = React.useRef<SVGSVGElement>(null);
  const tooltipRef = React.useRef<HTMLDivElement>(null);
  const [size, setSize] = React.useState({ width: propWidth ?? 600, height: propHeight ?? 400 });

  React.useEffect(() => {
    if (propWidth && propHeight) return;
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setSize({
          width: propWidth ?? entry.contentRect.width,
          height: propHeight ?? entry.contentRect.height,
        });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [propWidth, propHeight]);

  React.useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const svg = select(svgEl);
    const tooltip = select(tooltipRef.current);
    svg.selectAll("*").remove();

    const { width, height } = size;
    if (!width || !height || nodes.length === 0) return;

    const sizeValues = nodes.map((n) => n.size ?? 8);
    const medianSize = median(sizeValues) ?? 8;
    const sizeScale = scaleSqrt().domain([0, max(sizeValues) ?? 8]).range([4, 24]);

    const simNodes: SimNode[] = nodes.map((n) => ({
      id: n.id,
      label: n.label,
      group: n.group,
      radius: sizeScale(n.size ?? 8),
    }));

    const simLinks: SimLink[] = links.map((l) => ({
      source: l.source,
      target: l.target,
      weight: l.weight ?? 1,
    }));

    const color = scaleOrdinal(schemeTableau10);

    const simulation = forceSimulation(simNodes)
      .force(
        "link",
        forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance(60)
      )
      .force("charge", forceManyBody().strength(-120))
      .force("center", forceCenter(width / 2, height / 2))
      .force("collide", forceCollide<SimNode>().radius((d) => d.radius + 2));

    if (prefersReducedMotion) {
      simulation.stop();
      // Static circle layout for reduced-motion
      const r = Math.min(width, height) / 2 - 40;
      simNodes.forEach((n, i) => {
        const angle = (i / simNodes.length) * 2 * Math.PI;
        n.x = width / 2 + r * Math.cos(angle);
        n.y = height / 2 + r * Math.sin(angle);
      });
    }

    const g = svg.append("g");

    // Zoom
    const zoom = d3Zoom<SVGSVGElement, unknown>().scaleExtent([0.3, 5]).on("zoom", (event) => {
      g.attr("transform", event.transform);
    });
    svg.call(zoom);

    const link = g
      .append("g")
      .selectAll("line")
      .data(simLinks)
      .join("line")
      .attr("stroke", "hsl(var(--border))")
      .attr("stroke-width", (d) => Math.max(0.5, d.weight));

    const node = g
      .append("g")
      .selectAll<SVGCircleElement, SimNode>("circle")
      .data(simNodes)
      .join("circle")
      .attr("r", (d) => d.radius)
      .attr("fill", (d) => color(d.group))
      .attr("stroke", "hsl(var(--background))")
      .attr("stroke-width", 1.5)
      .style("cursor", "pointer")
      .on("mouseenter", (event, d) => {
        tooltip
          .style("display", "block")
          .style("left", `${event.offsetX + 10}px`)
          .style("top", `${event.offsetY - 10}px`)
          .html(`<strong>${d.label}</strong><br/>${d.group}`);
      })
      .on("mouseleave", () => tooltip.style("display", "none"))
      .on("click", (_event, d) => onNodeClick?.(d.id));

    // Drag behavior
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

    // Labels for larger nodes
    const labels = g
      .append("g")
      .selectAll("text")
      .data(simNodes.filter((n) => (n.radius >= sizeScale(medianSize))))
      .join("text")
      .text((d) => d.label)
      .attr("text-anchor", "middle")
      .attr("dy", (d) => -d.radius - 4)
      .attr("fill", "hsl(var(--foreground))")
      .style("font-size", "12px")
      .style("pointer-events", "none");

    simulation.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as SimNode).x ?? 0)
        .attr("y1", (d) => (d.source as SimNode).y ?? 0)
        .attr("x2", (d) => (d.target as SimNode).x ?? 0)
        .attr("y2", (d) => (d.target as SimNode).y ?? 0);

      node.attr("cx", (d) => d.x ?? 0).attr("cy", (d) => d.y ?? 0);

      labels.attr("x", (d) => d.x ?? 0).attr("y", (d) => d.y ?? 0);
    });

    return () => {
      simulation.stop();
    };
  }, [nodes, links, size, onNodeClick, prefersReducedMotion]);

  if (nodes.length === 0) {
    return <p className="text-sm text-muted-foreground text-center py-8">Sin datos disponibles</p>;
  }

  return (
    <div ref={containerRef} className={cn("relative w-full", className)} style={{ minHeight: size.height }}>
      <svg ref={svgRef} width={size.width} height={size.height} role="img" aria-label="Grafo de relaciones">
        <title>Grafo de relaciones</title>
      </svg>
      <div
        ref={tooltipRef}
        role="tooltip"
        className="absolute pointer-events-none hidden rounded bg-popover px-2 py-1 text-xs text-popover-foreground shadow border border-border"
      />
    </div>
  );
});
