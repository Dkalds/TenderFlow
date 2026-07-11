"use client";

import { getSeriesColor } from "@/lib/chart-colors";

export interface TreemapContentProps {
  /** Injected by Recharts at runtime */
  x?: number;
  /** Injected by Recharts at runtime */
  y?: number;
  /** Injected by Recharts at runtime */
  width?: number;
  /** Injected by Recharts at runtime */
  height?: number;
  /** Injected by Recharts at runtime */
  name?: string;
  /** Injected by Recharts at runtime */
  value?: number;
  /** Injected by Recharts at runtime */
  index?: number;
  /** Minimum width to render content (default: 40) */
  minWidth?: number;
  /** Minimum height to render content (default: 25) */
  minHeight?: number;
  /** Font size for name (default: 12) */
  fontSize?: number;
  /** Font size for value (default: 10) */
  valueFontSize?: number;
  /** Border radius (default: 4) */
  borderRadius?: number;
  /** Opacity for rectangle (default: 0.85) */
  opacity?: number;
  /** Format value for display (default: String) */
  formatValue?: (value: number) => string;
}

export function TreemapContent({
  x = 0,
  y = 0,
  width = 0,
  height = 0,
  name = "",
  value = 0,
  index = 0,
  minWidth = 40,
  minHeight = 25,
  fontSize = 12,
  valueFontSize = 10,
  borderRadius = 4,
  opacity = 0.85,
  formatValue = String,
}: TreemapContentProps) {
  if (width < minWidth || height < minHeight) return null;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={getSeriesColor(index)}
        rx={borderRadius}
        opacity={opacity}
      />
      {/* White labels are a deliberate exception: they sit on saturated categorical fills, not theme surfaces. */}
      <text x={x + 6} y={y + 16} fill="#fff" fontSize={fontSize} fontWeight={600}>
        {name.length > width / (fontSize * 0.6)
          ? `${name.slice(0, Math.floor(width / (fontSize * 0.6)))}…`
          : name}
      </text>
      {height > minHeight + 14 && (
        <text x={x + 6} y={y + 16 + fontSize + 4} fill="#fff" fontSize={valueFontSize} opacity={0.8}>
          {formatValue(value)}
        </text>
      )}
    </g>
  );
}
