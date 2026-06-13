"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { formatNumber } from "@/lib/utils";

interface CcaaData {
  ccaa: string;
  value: number;
}

interface SpainMapProps {
  data: CcaaData[];
  metric?: string;
  colorScale?: "blue" | "green" | "orange";
  height?: number;
  className?: string;
  onCcaaClick?: (ccaa: string) => void;
}

// Simplified schematic regions positioned in a grid-like map
// Each region is a polygon in a 600x500 viewBox
const CCAA_PATHS: Record<string, string> = {
  Galicia: "M 20,40 L 90,40 L 90,120 L 20,120 Z",
  Asturias: "M 95,40 L 170,40 L 170,85 L 95,85 Z",
  Cantabria: "M 175,40 L 235,40 L 235,85 L 175,85 Z",
  "País Vasco": "M 240,40 L 310,40 L 310,85 L 240,85 Z",
  Navarra: "M 315,40 L 385,40 L 385,100 L 315,100 Z",
  "La Rioja": "M 240,90 L 310,90 L 310,130 L 240,130 Z",
  Aragón: "M 315,105 L 420,105 L 420,230 L 315,230 Z",
  Cataluña: "M 425,40 L 530,40 L 530,180 L 425,180 Z",
  "Castilla y León": "M 20,125 L 235,125 L 235,230 L 20,230 Z",
  Madrid: "M 170,235 L 250,235 L 250,290 L 170,290 Z",
  "Castilla-La Mancha": "M 170,295 L 380,295 L 380,380 L 170,380 Z",
  "Comunidad Valenciana": "M 385,235 L 460,235 L 460,380 L 385,380 Z",
  Extremadura: "M 20,235 L 165,235 L 165,360 L 20,360 Z",
  Andalucía: "M 20,365 L 380,365 L 380,470 L 20,470 Z",
  Murcia: "M 385,385 L 460,385 L 460,440 L 385,440 Z",
  "Islas Baleares": "M 470,200 L 570,200 L 570,260 L 470,260 Z",
  "Canarias": "M 20,485 L 160,485 L 160,540 L 20,540 Z",
  Ceuta: "M 175,450 L 195,450 L 195,470 L 175,470 Z",
  Melilla: "M 200,450 L 220,450 L 220,470 L 200,470 Z",
};

// Name normalization map
const CCAA_ALIASES: Record<string, string> = {
  "comunidad de madrid": "Madrid",
  "madrid": "Madrid",
  "cataluña": "Cataluña",
  "catalunya": "Cataluña",
  "país vasco": "País Vasco",
  "euskadi": "País Vasco",
  "pais vasco": "País Vasco",
  "comunidad valenciana": "Comunidad Valenciana",
  "comunitat valenciana": "Comunidad Valenciana",
  "valencia": "Comunidad Valenciana",
  "andalucía": "Andalucía",
  "andalucia": "Andalucía",
  "castilla y león": "Castilla y León",
  "castilla y leon": "Castilla y León",
  "castilla-la mancha": "Castilla-La Mancha",
  "castilla la mancha": "Castilla-La Mancha",
  "galicia": "Galicia",
  "asturias": "Asturias",
  "principado de asturias": "Asturias",
  "cantabria": "Cantabria",
  "navarra": "Navarra",
  "comunidad foral de navarra": "Navarra",
  "la rioja": "La Rioja",
  "aragón": "Aragón",
  "aragon": "Aragón",
  "extremadura": "Extremadura",
  "murcia": "Murcia",
  "región de murcia": "Murcia",
  "region de murcia": "Murcia",
  "islas baleares": "Islas Baleares",
  "illes balears": "Islas Baleares",
  "baleares": "Islas Baleares",
  "canarias": "Canarias",
  "islas canarias": "Canarias",
  "ceuta": "Ceuta",
  "melilla": "Melilla",
};

function normalizeCcaa(name: string): string {
  const lower = name.toLowerCase().trim();
  return CCAA_ALIASES[lower] ?? name;
}

const COLOR_SCALES = {
  blue: { light: "hsl(210 100% 95%)", dark: "hsl(210 100% 35%)" },
  green: { light: "hsl(140 60% 92%)", dark: "hsl(140 60% 30%)" },
  orange: { light: "hsl(30 100% 92%)", dark: "hsl(30 100% 40%)" },
};

function interpolateColor(t: number, scale: "blue" | "green" | "orange"): string {
  const s = COLOR_SCALES[scale];
  // Parse HSL components and interpolate
  const parse = (c: string) => {
    const m = c.match(/hsl\((\d+)\s+(\d+)%\s+(\d+)%\)/);
    return m ? { h: +m[1], s: +m[2], l: +m[3] } : { h: 0, s: 0, l: 50 };
  };
  const from = parse(s.light);
  const to = parse(s.dark);
  const h = from.h + (to.h - from.h) * t;
  const sat = from.s + (to.s - from.s) * t;
  const l = from.l + (to.l - from.l) * t;
  return `hsl(${h} ${sat}% ${l}%)`;
}

export const SpainMap = React.memo(function SpainMap({
  data,
  metric = "Valor",
  colorScale = "blue",
  height = 500,
  className,
  onCcaaClick,
}: SpainMapProps) {
  const [hoveredCcaa, setHoveredCcaa] = React.useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = React.useState({ x: 0, y: 0 });

  const valueMap = React.useMemo(() => {
    const map = new Map<string, number>();
    for (const d of data) {
      map.set(normalizeCcaa(d.ccaa), d.value);
    }
    return map;
  }, [data]);

  const { minVal, maxVal } = React.useMemo(() => {
    const values = data.map((d) => d.value);
    return { minVal: Math.min(...values, 0), maxVal: Math.max(...values, 1) };
  }, [data]);

  const getColor = (ccaa: string) => {
    const val = valueMap.get(ccaa);
    if (val == null) return "hsl(var(--muted))";
    const t = maxVal === minVal ? 0.5 : (val - minVal) / (maxVal - minVal);
    return interpolateColor(t, colorScale);
  };

  const hoveredValue = hoveredCcaa ? valueMap.get(hoveredCcaa) : undefined;

  return (
    <div className={cn("relative w-full", className)}>
      <svg viewBox="0 0 580 550" style={{ height, width: "100%" }} className="block" role="img" aria-label="Mapa de España">
        <title>Mapa de España</title>
        {Object.entries(CCAA_PATHS).map(([name, path]) => (
          <path
            key={name}
            d={path}
            fill={getColor(name)}
            stroke={hoveredCcaa === name ? "hsl(var(--foreground))" : "hsl(var(--border))"}
            strokeWidth={hoveredCcaa === name ? 2.5 : 1}
            className="cursor-pointer motion-safe:transition-colors"
            tabIndex={0}
            role="button"
            aria-label={name}
            onMouseEnter={(e) => {
              setHoveredCcaa(name);
              const rect = (e.target as SVGPathElement).ownerSVGElement?.getBoundingClientRect();
              setTooltipPos({
                x: e.clientX - (rect?.left ?? 0),
                y: e.clientY - (rect?.top ?? 0) - 10,
              });
            }}
            onMouseMove={(e) => {
              const rect = (e.target as SVGPathElement).ownerSVGElement?.getBoundingClientRect();
              setTooltipPos({
                x: e.clientX - (rect?.left ?? 0),
                y: e.clientY - (rect?.top ?? 0) - 10,
              });
            }}
            onMouseLeave={() => setHoveredCcaa(null)}
            onClick={() => onCcaaClick?.(name)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onCcaaClick?.(name);
              }
            }}
          />
        ))}
        {/* Labels for each CCAA */}
        {Object.entries(CCAA_PATHS).map(([name, path]) => {
          // Calculate center from path
          const nums = path.match(/[\d.]+/g)?.map(Number) ?? [];
          const xs: number[] = [];
          const ys: number[] = [];
          for (let i = 0; i < nums.length; i += 2) {
            xs.push(nums[i]);
            ys.push(nums[i + 1]);
          }
          const cx = xs.reduce((a, b) => a + b, 0) / xs.length;
          const cy = ys.reduce((a, b) => a + b, 0) / ys.length;
          const isSmall = name === "Ceuta" || name === "Melilla" || name === "La Rioja";
          return (
            <text
              key={`label-${name}`}
              x={cx}
              y={cy}
              textAnchor="middle"
              dominantBaseline="central"
              fill="hsl(var(--foreground))"
              fontSize={isSmall ? 12 : 12}
              className="pointer-events-none select-none"
            >
              {name}
            </text>
          );
        })}
      </svg>

      {/* Tooltip */}
      {hoveredCcaa && (
        <div
          role="tooltip"
          className="absolute z-20 rounded border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow pointer-events-none -translate-x-1/2 -translate-y-full"
          style={{ left: tooltipPos.x, top: tooltipPos.y }}
        >
          <p className="font-medium">{hoveredCcaa}</p>
          <p>{metric}: {hoveredValue != null ? formatNumber(hoveredValue) : "Sin datos"}</p>
        </div>
      )}
    </div>
  );
});
