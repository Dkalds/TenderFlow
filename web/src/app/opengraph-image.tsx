import { ImageResponse } from "next/og";
import { CONTENIDO } from "@/app/(publico)/_content/landing";
import { MARCA_HEX, TF_MARK_PATHS, TF_MARK_STROKE, TF_MARK_VIEWBOX } from "@/lib/marca";
import { SITE_NAME } from "@/lib/site";

export const alt = `${SITE_NAME} — Radar de licitaciones TI del sector público español`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * Imagen Open Graph por defecto: lo que ve quien recibe un enlace de TenderFlow
 * en Slack, LinkedIn, WhatsApp o un correo. Lleva el rótulo y el titular del
 * hero de la landing, **leídos de `CONTENIDO`** y no copiados: la copia a mano
 * se quedó con el titular anterior al rediseño de 2026-09 mientras la portada
 * ya decía otro. Las cuatro bandas de score son la firma visual, para que el
 * unfurl y la página se reconozcan como la misma cosa.
 *
 * Esto se renderiza con Satori fuera del navegador: no hay cascada, ni
 * `hsl(var(--primary))`, ni Tailwind. Por eso la marca —el trazo del monograma
 * y sus hex— sale de `lib/marca.ts`, la única copia que comparten el logo, las
 * dos OG y `global-error`. Las bandas siguen aquí, en el hex de la paleta
 * oscura de `--score-hot/warm/cold/skip`: son del scoring, no de la marca.
 *
 * Satori sólo implementa un subconjunto de CSS: flexbox sí, grid no, y todo
 * contenedor con más de un hijo necesita `display: "flex"` explícito.
 */

/* Bandas reales del scoring (Radar), en el hex de la paleta oscura. */
const BANDAS = [
  { nombre: "Caliente", color: "#E44444" },
  { nombre: "Atractiva", color: "#F4C025" },
  { nombre: "Tibia", color: "#4C99E6" },
  { nombre: "Descarte", color: "#96A1A6" },
];

export default function Image() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        backgroundColor: MARCA_HEX.tinta,
        padding: "72px 80px",
        fontFamily: "sans-serif",
      }}
    >
      {/* Marca */}
      <div style={{ display: "flex", alignItems: "center" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: 76,
            height: 76,
            borderRadius: 20,
            backgroundColor: MARCA_HEX.naranja,
            marginRight: 24,
          }}
        >
          {/* Ligatura TF, misma construcción que `TenderFlowLogo` */}
          <svg
            width={44}
            height={44}
            viewBox={TF_MARK_VIEWBOX}
            fill="none"
            stroke={MARCA_HEX.tinta}
            strokeWidth={TF_MARK_STROKE}
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            {TF_MARK_PATHS.map((d) => (
              <path key={d} d={d} />
            ))}
          </svg>
        </div>
        <div
          style={{
            fontSize: 42,
            fontWeight: 700,
            color: MARCA_HEX.papel,
            letterSpacing: "-0.02em",
          }}
        >
          {SITE_NAME}
        </div>
      </div>

      {/* Posicionamiento: el rótulo y el titular del hero, de su fuente. El
          rótulo en versal gris, como el KICKER de la superficie pública. */}
      <div style={{ display: "flex", flexDirection: "column" }}>
        <div
          style={{
            display: "flex",
            fontSize: 26,
            fontWeight: 600,
            color: MARCA_HEX.gris,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            marginBottom: 24,
          }}
        >
          {CONTENIDO.eyebrow}
        </div>
        <div
          style={{
            display: "flex",
            fontSize: 64,
            fontWeight: 700,
            color: MARCA_HEX.papel,
            lineHeight: 1.15,
            letterSpacing: "-0.03em",
            maxWidth: 980,
          }}
        >
          {CONTENIDO.h1}
        </div>
      </div>

      {/* Pie: las cuatro bandas de score, la firma visual del producto */}
      <div style={{ display: "flex", alignItems: "center" }}>
        {BANDAS.map((banda) => (
          <div
            key={banda.nombre}
            style={{
              display: "flex",
              alignItems: "center",
              marginRight: 36,
            }}
          >
            <div
              style={{
                display: "flex",
                width: 16,
                height: 16,
                borderRadius: 8,
                backgroundColor: banda.color,
                marginRight: 12,
              }}
            />
            <div style={{ display: "flex", fontSize: 28, color: MARCA_HEX.gris }}>{banda.nombre}</div>
          </div>
        ))}
      </div>
    </div>,
    size,
  );
}
