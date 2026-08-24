"use client";

import * as React from "react";
import type { FeatureCollection, Feature, Geometry } from "geojson";
import type { Layer, LeafletMouseEvent } from "leaflet";
import { GeoJSON, MapContainer, ZoomControl } from "react-leaflet";
// El CSS de Leaflet se importaba en el layout raíz, así que la landing pública
// —donde no hay mapa— se llevaba 16 KB de estilos y los PNG de los marcadores.
// Va con el único componente que lo usa.
import "leaflet/dist/leaflet.css";
import { useTheme } from "next-themes";
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

// Maps GeoJSON "name" → canonical name used by the app
const GEO_TO_CANONICAL: Record<string, string> = {
  "Castilla-Leon": "Castilla y León",
  Cataluña: "Cataluña",
  Ceuta: "Ceuta",
  Murcia: "Murcia",
  "La Rioja": "La Rioja",
  Baleares: "Islas Baleares",
  Canarias: "Canarias",
  Cantabria: "Cantabria",
  Andalucia: "Andalucía",
  Asturias: "Asturias",
  Valencia: "Comunidad Valenciana",
  Melilla: "Melilla",
  Navarra: "Navarra",
  Galicia: "Galicia",
  Aragon: "Aragón",
  Madrid: "Madrid",
  Extremadura: "Extremadura",
  "Castilla-La Mancha": "Castilla-La Mancha",
  "Pais Vasco": "País Vasco",
};

// Name normalization for incoming data
const CCAA_ALIASES: Record<string, string> = {
  "comunidad de madrid": "Madrid",
  madrid: "Madrid",
  cataluña: "Cataluña",
  catalunya: "Cataluña",
  "país vasco": "País Vasco",
  euskadi: "País Vasco",
  "pais vasco": "País Vasco",
  "comunidad valenciana": "Comunidad Valenciana",
  "comunitat valenciana": "Comunidad Valenciana",
  valencia: "Comunidad Valenciana",
  andalucía: "Andalucía",
  andalucia: "Andalucía",
  "castilla y león": "Castilla y León",
  "castilla y leon": "Castilla y León",
  "castilla-la mancha": "Castilla-La Mancha",
  "castilla la mancha": "Castilla-La Mancha",
  galicia: "Galicia",
  asturias: "Asturias",
  "principado de asturias": "Asturias",
  cantabria: "Cantabria",
  navarra: "Navarra",
  "comunidad foral de navarra": "Navarra",
  "la rioja": "La Rioja",
  aragón: "Aragón",
  aragon: "Aragón",
  extremadura: "Extremadura",
  murcia: "Murcia",
  "región de murcia": "Murcia",
  "region de murcia": "Murcia",
  "islas baleares": "Islas Baleares",
  "illes balears": "Islas Baleares",
  baleares: "Islas Baleares",
  canarias: "Canarias",
  "islas canarias": "Canarias",
  ceuta: "Ceuta",
  melilla: "Melilla",
};

function normalizeCcaa(name: string): string {
  const lower = name.toLowerCase().trim();
  return CCAA_ALIASES[lower] ?? name;
}

const COLOR_SCALES = {
  light: {
    blue: { light: "hsl(197 40% 93%)", dark: "hsl(197 70% 30%)" },
    green: { light: "hsl(150 45% 92%)", dark: "hsl(152 70% 26%)" },
    orange: { light: "hsl(26 70% 93%)", dark: "hsl(22 80% 38%)" },
  },
  dark: {
    blue: { light: "hsl(198 30% 12%)", dark: "hsl(194 85% 60%)" },
    green: { light: "hsl(155 30% 12%)", dark: "hsl(150 65% 48%)" },
    orange: { light: "hsl(24 30% 12%)", dark: "hsl(26 90% 60%)" },
  },
} as const;

function interpolateColor(t: number, scale: "blue" | "green" | "orange", mode: "light" | "dark"): string {
  const s = COLOR_SCALES[mode][scale];
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

function formatCompact(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return formatNumber(n);
}

export const SpainMap = React.memo(function SpainMap({
  data,
  metric = "Valor",
  colorScale = "blue",
  height = 500,
  className,
  onCcaaClick,
}: SpainMapProps) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  const [geoData, setGeoData] = React.useState<FeatureCollection | null>(null);
  const [geoError, setGeoError] = React.useState(false);
  const [hoveredCcaa, setHoveredCcaa] = React.useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = React.useState({ x: 0, y: 0 });

  React.useEffect(() => {
    let cancelled = false;
    fetch("/spain-ccaa.json")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d: FeatureCollection) => {
        if (!cancelled) setGeoData(d);
      })
      .catch(() => {
        if (!cancelled) setGeoError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  const getColor = React.useCallback(
    (ccaa: string) => {
      const val = valueMap.get(ccaa);
      if (val == null) return dark ? "hsl(200 15% 16%)" : "hsl(200 15% 92%)";
      const t = maxVal === minVal ? 0.5 : (val - minVal) / (maxVal - minVal);
      return interpolateColor(t, colorScale, dark ? "dark" : "light");
    },
    [valueMap, minVal, maxVal, colorScale, dark],
  );

  const hoveredValue = hoveredCcaa ? valueMap.get(hoveredCcaa) : undefined;

  const style = React.useCallback(
    (feature: Feature<Geometry, { name: string }> | undefined) => {
      const geoName = feature?.properties?.name ?? "";
      const canonical = GEO_TO_CANONICAL[geoName] ?? geoName;
      const isHovered = canonical === hoveredCcaa;
      return {
        fillColor: getColor(canonical),
        fillOpacity: 0.85,
        color: dark
          ? isHovered
            ? "hsl(36 12% 90%)"
            : "hsl(200 15% 40%)"
          : isHovered
            ? "hsl(204 35% 15%)"
            : "hsl(200 15% 55%)",
        weight: isHovered ? 2.5 : 1,
      };
    },
    [getColor, hoveredCcaa, dark],
  );

  const onEachFeature = React.useCallback(
    (feature: Feature<Geometry, { name: string }>, layer: Layer) => {
      const geoName = feature.properties?.name ?? "";
      const canonical = GEO_TO_CANONICAL[geoName] ?? geoName;
      const val = valueMap.get(canonical);
      const label = val != null ? formatCompact(val) : "";

      // Permanent label in the center of each region
      if ("bindTooltip" in layer && typeof layer.bindTooltip === "function") {
        (layer as Layer & { bindTooltip: (content: string, opts: Record<string, unknown>) => void }).bindTooltip(
          `<div style="text-align:center;font-weight:600;font-size:11px;line-height:1.2">
            ${canonical}<br/>
            <span style="font-size:13px">${label}</span>
          </div>`,
          {
            permanent: true,
            direction: "center",
            className: "ccaa-label",
          },
        );
      }

      if ("on" in layer && typeof layer.on === "function") {
        layer.on({
          mouseover: () => setHoveredCcaa(canonical),
          mouseout: () => setHoveredCcaa(null),
          mousemove: (e: LeafletMouseEvent) => {
            setTooltipPos({ x: e.containerPoint.x, y: e.containerPoint.y });
          },
          click: () => onCcaaClick?.(canonical),
        });
      }
    },
    [valueMap, onCcaaClick],
  );

  if (!geoData) {
    return (
      <div
        className={cn("border-border bg-muted/30 flex items-center justify-center rounded-md border", className)}
        style={{ height }}
      >
        <span className="text-muted-foreground text-sm">{geoError ? "Error cargando mapa" : "Cargando mapa…"}</span>
      </div>
    );
  }

  return (
    <div className={cn("border-border relative w-full overflow-hidden rounded-md border", className)}>
      <MapContainer
        center={[40.0, -3.7]}
        zoom={6}
        minZoom={5}
        maxZoom={8}
        zoomControl={false}
        scrollWheelZoom
        style={{ height, width: "100%", background: "hsl(var(--card))" }}
      >
        <ZoomControl position="bottomright" />
        <GeoJSON
          key={`${colorScale}-${data.length}-${maxVal}-${resolvedTheme}`}
          data={geoData}
          style={style}
          onEachFeature={onEachFeature}
        />
      </MapContainer>

      {/* Hover tooltip */}
      {hoveredCcaa && (
        <div
          role="tooltip"
          className="border-border bg-popover text-popover-foreground pointer-events-none absolute z-[1000] -translate-x-1/2 -translate-y-full rounded border px-2.5 py-1.5 text-xs shadow-md"
          style={{ left: tooltipPos.x, top: tooltipPos.y - 12 }}
        >
          <p className="font-semibold">{hoveredCcaa}</p>
          <p>
            {metric}: {hoveredValue != null ? formatNumber(hoveredValue) : "Sin datos"}
          </p>
        </div>
      )}
    </div>
  );
});
