"use client";

import * as React from "react";
import { select } from "d3-selection";
import { sum } from "d3-array";
import { scaleOrdinal } from "d3-scale";
import { interpolateNumber } from "d3-interpolate";
import { cn } from "@/lib/utils";

interface SankeyNode {
  id: string;
  label: string;
}

interface SankeyLink {
  source: string;
  target: string;
  value: number;
}

interface SankeyChartProps {
  nodes: SankeyNode[];
  links: SankeyLink[];
  width?: number;
  height?: number;
  className?: string;
}

interface LayoutNode extends SankeyNode {
  x: number;
  y: number;
  dy: number;
  column: number;
}

interface LayoutLink {
  source: LayoutNode;
  target: LayoutNode;
  value: number;
  sy: number;
  ty: number;
  dy: number;
}

export const SankeyChart = React.memo(function SankeyChart({
  nodes,
  links,
  width: propWidth,
  height: propHeight,
  className,
}: SankeyChartProps) {
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
    const svg = select(svgRef.current);
    const tooltip = select(tooltipRef.current);
    svg.selectAll("*").remove();

    const { width, height } = size;
    const padding = 20;
    // Node width: 20px (layout chart, full 44px touch target not applicable here)
    const nodeWidth = 20;

    // Determine source and target sets
    const sourceIds = new Set(links.map((l) => l.source));
    const targetIds = new Set(links.map((l) => l.target));

    // Nodes only in source (left), only in target (right), in both (left)
    const layoutNodes: LayoutNode[] = nodes.map((n) => ({
      ...n,
      column: targetIds.has(n.id) && !sourceIds.has(n.id) ? 1 : 0,
      x: 0,
      y: 0,
      dy: 0,
    }));

    const leftNodes = layoutNodes.filter((n) => n.column === 0);
    const rightNodes = layoutNodes.filter((n) => n.column === 1);

    const nodeMap = new Map(layoutNodes.map((n) => [n.id, n]));

    // Compute node sizes proportional to total flow
    const totalValue = sum(links, (l) => l.value) || 1;

    for (const n of layoutNodes) {
      const outFlow = sum(links.filter((l) => l.source === n.id), (l) => l.value);
      const inFlow = sum(links.filter((l) => l.target === n.id), (l) => l.value);
      n.dy = Math.max(outFlow, inFlow);
    }

    const usableHeight = height - padding * 2;

    const layoutColumn = (col: LayoutNode[]) => {
      const colTotal = sum(col, (n) => n.dy) || 1;
      const gap = Math.min(8, (usableHeight - (usableHeight * 0.8)) / Math.max(col.length - 1, 1));
      const scale = (usableHeight - gap * (col.length - 1)) / colTotal;
      let y = padding;
      for (const n of col) {
        n.dy = n.dy * scale;
        n.y = y;
        y += n.dy + gap;
      }
    };

    layoutColumn(leftNodes);
    layoutColumn(rightNodes);

    for (const n of leftNodes) n.x = padding;
    for (const n of rightNodes) n.x = width - padding - nodeWidth;

    // Build layout links
    const layoutLinks: LayoutLink[] = [];
    const sourceOffsets = new Map<string, number>();
    const targetOffsets = new Map<string, number>();
    for (const n of layoutNodes) {
      sourceOffsets.set(n.id, 0);
      targetOffsets.set(n.id, 0);
    }

    for (const l of links) {
      const s = nodeMap.get(l.source);
      const t = nodeMap.get(l.target);
      if (!s || !t) continue;
      const sTotal = sum(links.filter((ll) => ll.source === l.source), (ll) => ll.value) || 1;
      const tTotal = sum(links.filter((ll) => ll.target === l.target), (ll) => ll.value) || 1;
      const dy_s = (l.value / sTotal) * s.dy;
      const dy_t = (l.value / tTotal) * t.dy;
      const dy = Math.min(dy_s, dy_t);
      const sy = sourceOffsets.get(l.source) ?? 0;
      const ty = targetOffsets.get(l.target) ?? 0;
      layoutLinks.push({
        source: s,
        target: t,
        value: l.value,
        sy,
        ty,
        dy,
      });
      sourceOffsets.set(l.source, sy + dy);
      targetOffsets.set(l.target, ty + dy);
    }

    const colorScale = scaleOrdinal<string>()
      .domain(["0", "1"])
      .range(["hsl(var(--primary))", "hsl(var(--muted-foreground))"]);

    // Draw links
    svg
      .append("g")
      .selectAll("path")
      .data(layoutLinks)
      .join("path")
      .attr("d", (d) => {
        const x0 = d.source.x + nodeWidth;
        const x1 = d.target.x;
        const y0 = d.source.y + d.sy + d.dy / 2;
        const y1 = d.target.y + d.ty + d.dy / 2;
        const curvature = 0.5;
        const xi = interpolateNumber(x0, x1);
        const x2 = xi(curvature);
        const x3 = xi(1 - curvature);
        return `M${x0},${y0}C${x2},${y0} ${x3},${y1} ${x1},${y1}`;
      })
      .attr("stroke", (d) => colorScale(String(d.source.column)))
      .attr("stroke-opacity", 0.3)
      .attr("stroke-width", (d) => Math.max(1, d.dy))
      .attr("fill", "none")
      .on("mouseenter", (event, d) => {
        tooltip
          .style("display", "block")
          .style("left", `${event.offsetX + 10}px`)
          .style("top", `${event.offsetY - 10}px`)
          .text(`${d.source.label} → ${d.target.label}: ${d.value}`);
      })
      .on("mouseleave", () => tooltip.style("display", "none"));

    // Draw nodes
    svg
      .append("g")
      .selectAll("rect")
      .data(layoutNodes)
      .join("rect")
      .attr("x", (d) => d.x)
      .attr("y", (d) => d.y)
      .attr("width", nodeWidth)
      .attr("height", (d) => Math.max(1, d.dy))
      .attr("fill", (d) => colorScale(String(d.column)))
      .attr("rx", 2)
      .attr("tabindex", 0)
      .on("mouseenter", (event, d) => {
        const flow = d.column === 0
          ? sum(links.filter((l) => l.source === d.id), (l) => l.value)
          : sum(links.filter((l) => l.target === d.id), (l) => l.value);
        tooltip
          .style("display", "block")
          .style("left", `${event.offsetX + 10}px`)
          .style("top", `${event.offsetY - 10}px`)
          .text(`${d.label}: ${flow}`);
      })
      .on("mouseleave", () => tooltip.style("display", "none"))
      // TODO: full keyboard nav requires D3 refactor
      .on("focus", (event, d) => {
        const flow = d.column === 0
          ? sum(links.filter((l) => l.source === d.id), (l) => l.value)
          : sum(links.filter((l) => l.target === d.id), (l) => l.value);
        const rect = (event.target as SVGRectElement).getBoundingClientRect();
        const parentRect = (event.target as SVGRectElement).ownerSVGElement?.getBoundingClientRect();
        tooltip
          .style("display", "block")
          .style("left", `${rect.left - (parentRect?.left ?? 0) + rect.width + 4}px`)
          .style("top", `${rect.top - (parentRect?.top ?? 0)}px`)
          .text(`${d.label}: ${flow}`);
      })
      .on("blur", () => tooltip.style("display", "none"));

    // Draw labels
    svg
      .append("g")
      .selectAll("text")
      .data(layoutNodes)
      .join("text")
      .attr("x", (d) => (d.column === 0 ? d.x - 4 : d.x + nodeWidth + 4))
      .attr("y", (d) => d.y + d.dy / 2)
      .attr("dy", "0.35em")
      .attr("text-anchor", (d) => (d.column === 0 ? "end" : "start"))
      .attr("fill", "hsl(var(--foreground))")
      .style("font-size", "12px")
      .text((d) => d.label);
  }, [nodes, links, size]);

  return (
    <div ref={containerRef} className={cn("relative w-full", className)} style={{ minHeight: size.height }}>
      <svg ref={svgRef} width={size.width} height={size.height} role="img" aria-label="Diagrama Sankey">
        <title>Diagrama Sankey</title>
      </svg>
      <div
        ref={tooltipRef}
        role="tooltip"
        className="absolute pointer-events-none hidden rounded bg-popover px-2 py-1 text-xs text-popover-foreground shadow border border-border"
      />
    </div>
  );
});
