import { ImageResponse } from "next/og";
import { SITE_NAME } from "@/lib/site";

export const alt = `${SITE_NAME} — Inteligencia de licitaciones del sector público español`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * Imagen Open Graph por defecto: lo que ve quien recibe un enlace de TenderFlow
 * en Slack, LinkedIn, WhatsApp o un correo.
 *
 * Los colores están escritos a mano en hexadecimal en vez de leerse de las
 * variables CSS porque esto se renderiza con Satori fuera del navegador: no hay
 * cascada, ni `hsl(var(--primary))`, ni Tailwind. Son el equivalente literal de
 * la paleta oscura de `globals.css` (`--background: 200 32% 5%`,
 * `--primary: 26 88% 62%`, `--foreground: 36 12% 93%`); si cambia la marca,
 * este fichero no se entera solo.
 *
 * Satori sólo implementa un subconjunto de CSS: flexbox sí, grid no, y todo
 * contenedor con más de un hijo necesita `display: "flex"` explícito.
 */
export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          backgroundColor: "#090E11",
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
              backgroundColor: "#F39349",
              marginRight: 24,
            }}
          >
            {/* Ligatura TF, misma construcción que `TenderFlowLogo` */}
            <svg
              width={44}
              height={44}
              viewBox="0 0 24 24"
              fill="none"
              stroke="#090E11"
              strokeWidth={2.7}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3.5 6 H20.5" />
              <path d="M12 6 V19" />
              <path d="M12 12 H18.5" />
            </svg>
          </div>
          <div
            style={{
              fontSize: 42,
              fontWeight: 700,
              color: "#EFEEEB",
              letterSpacing: "-0.02em",
            }}
          >
            {SITE_NAME}
          </div>
        </div>

        {/* Titular */}
        <div
          style={{
            display: "flex",
            fontSize: 68,
            fontWeight: 700,
            color: "#EFEEEB",
            lineHeight: 1.15,
            letterSpacing: "-0.03em",
            maxWidth: 900,
          }}
        >
          Inteligencia de licitaciones del sector público español
        </div>

        {/* Pie */}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div
            style={{
              display: "flex",
              width: 132,
              height: 6,
              borderRadius: 3,
              backgroundColor: "#F39349",
              marginBottom: 28,
            }}
          />
          <div style={{ display: "flex", fontSize: 30, color: "#8A9199" }}>
            Seguimiento de concursos · Análisis competitivo · Alertas
          </div>
        </div>
      </div>
    ),
    size,
  );
}
