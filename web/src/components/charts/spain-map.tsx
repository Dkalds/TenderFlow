"use client";

import * as React from "react";
import type { LatLngExpression } from "leaflet";
import { CircleMarker, MapContainer, TileLayer, Tooltip, ZoomControl } from "react-leaflet";
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

const CCAA_COORDS: Record<string, [number, number]> = {
  Galicia: [42.75, -8.5],
  Asturias: [43.35, -5.85],
  Cantabria: [43.2, -4.0],
  "País Vasco": [43.0, -2.55],
  Navarra: [42.67, -1.65],
  "La Rioja": [42.3, -2.45],
  Aragón: [41.65, -0.9],
  Cataluña: [41.75, 1.65],
  "Castilla y León": [41.7, -4.75],
  Madrid: [40.42, -3.7],
  "Castilla-La Mancha": [39.5, -3.0],
  "Comunidad Valenciana": [39.48, -0.4],
  Extremadura: [39.0, -6.0],
  Andalucía: [37.45, -4.5],
  Murcia: [37.98, -1.13],
  "Islas Baleares": [39.6, 2.9],
  Canarias: [28.4, -15.5],
  Ceuta: [35.89, -5.31],
  Melilla: [35.29, -2.94],
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

  const getRadius = (ccaa: string) => {
    const val = valueMap.get(ccaa);
    if (val == null) return 7;
    const t = maxVal === minVal ? 0.5 : (val - minVal) / (maxVal - minVal);
    return 7 + t * 15;
  };

  const points = React.useMemo(
    () =>
      Object.entries(CCAA_COORDS).map(([ccaa, latlng]) => ({
        ccaa,
        latlng: latlng as LatLngExpression,
      })),
    [],
  );

  return (
    <div className={cn("relative w-full overflow-hidden rounded-md border border-border", className)}>
      <MapContainer
        center={[40.2, -3.7]}
        zoom={5}
        minZoom={4}
        maxZoom={9}
        zoomControl={false}
        scrollWheelZoom
        style={{ height, width: "100%" }}
      >
        <ZoomControl position="bottomright" />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {points.map(({ ccaa, latlng }) => {
          const value = valueMap.get(ccaa);
          return (
            <CircleMarker
              key={ccaa}
              center={latlng}
              radius={getRadius(ccaa)}
              pathOptions={{
                color: "hsl(var(--foreground))",
                weight: 1.2,
                fillColor: getColor(ccaa),
                fillOpacity: value == null ? 0.4 : 0.85,
              }}
              eventHandlers={{
                click: () => onCcaaClick?.(ccaa),
              }}
            >
              <Tooltip direction="top" offset={[0, -8]} opacity={0.98}>
                <div className="text-xs">
                  <p className="font-medium">{ccaa}</p>
                  <p>
                    {metric}: {value != null ? formatNumber(value) : "Sin datos"}
                  </p>
                </div>
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
});
