"use client";

import * as React from "react";
import { AreaChart, Area, ResponsiveContainer, YAxis } from "recharts";

interface MiniSparklineProps {
  data: number[];
  /** true = green (uptrend is good), false = red (uptrend is bad) */
  up?: boolean;
  width?: number;
  height?: number;
  className?: string;
}

export const MiniSparkline = React.memo(function MiniSparkline({
  data,
  up = true,
  width = 80,
  height = 28,
  className,
}: MiniSparklineProps) {
  if (!data || data.length < 2) return null;

  const chartData = data.map((v, i) => ({ v, i }));
  const color = up ? "hsl(83 69% 44%)" : "hsl(0 72% 51%)";

  return (
    <div className={className} style={{ width, height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 1, right: 1, bottom: 1, left: 1 }}>
          <YAxis domain={["dataMin", "dataMax"]} hide />
          <Area
            type="monotone"
            dataKey="v"
            stroke={color}
            strokeWidth={1.5}
            fill={color}
            fillOpacity={0.15}
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
});
