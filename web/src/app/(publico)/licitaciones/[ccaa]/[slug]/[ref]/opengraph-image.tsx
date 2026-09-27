import { ImageResponse } from "next/og";
import { MARCA_HEX, TF_MARK_PATHS, TF_MARK_STROKE, TF_MARK_VIEWBOX } from "@/lib/marca";
import { obtenerLicitacion } from "@/lib/publico-api";
import { SITE_NAME } from "@/lib/site";
import { formatCurrency } from "@/lib/utils";

export const alt = `Ficha de licitación en ${SITE_NAME}`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const revalidate = 3600;

/**
 * Open Graph por ficha: el unfurl de una licitación compartida en Slack o
 * LinkedIn muestra el anuncio —título, órgano, presupuesto, CPV y fuente— en
 * vez de la tarjeta genérica del sitio. Todos los valores salen del mismo
 * endpoint que pinta la página (ADR-014: nada se calcula aquí), y por la
 * prioridad de los metadatos por convención de fichero este segmento deja de
 * usar la imagen genérica sin tocar nada más.
 *
 * La marca —trazo del monograma y hex— sale de `lib/marca.ts`, como en
 * `app/opengraph-image.tsx`: Satori renderiza fuera del navegador, sin
 * variables CSS ni Tailwind, y dos copias a mano del mismo naranja ya habían
 * divergido. Mismas reglas de Satori: flexbox sí, grid no, `display: "flex"`
 * explícito en todo contenedor con más de un hijo.
 */

const TINTA = MARCA_HEX.papel;
const FONDO = MARCA_HEX.tinta;
const NARANJA = MARCA_HEX.naranja;
const GRIS = MARCA_HEX.gris;

function Chip({ texto }: { texto: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        border: "1.5px solid #2A343B",
        borderRadius: 999,
        padding: "8px 20px",
        fontSize: 24,
        color: GRIS,
        marginRight: 16,
      }}
    >
      {texto}
    </div>
  );
}

export default async function Image({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  // `lic` en `null` es el 404 confirmado por la API, y para él sí vale la
  // tarjeta genérica de más abajo. Un fallo de red no llega hasta aquí: lanza,
  // y con ISR eso deja en pie la imagen ya generada — mucho mejor que sustituir
  // el unfurl de un anuncio real por la tarjeta de relleno.
  const lic = await obtenerLicitacion(ref);

  // Título recortado a lo que cabe en dos líneas grandes; el corte con elipsis
  // es preferible a encoger la letra hasta lo ilegible.
  const titulo = lic ? (lic.titulo.length > 120 ? `${lic.titulo.slice(0, 119)}…` : lic.titulo) : null;
  const organo = lic?.organo_contratacion
    ? lic.organo_contratacion.length > 80
      ? `${lic.organo_contratacion.slice(0, 79)}…`
      : lic.organo_contratacion
    : null;

  const chips = lic
    ? [
        lic.importe ? formatCurrency(lic.importe) : null,
        lic.cpv ? `CPV ${lic.cpv}` : null,
        lic.ccaa ?? null,
        lic.fuente === "ted" ? "TED" : "PLACSP",
      ].filter((chip): chip is string => Boolean(chip))
    : [];

  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        backgroundColor: FONDO,
        padding: "64px 80px",
        fontFamily: "sans-serif",
      }}
    >
      {/* Marca + categoría */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 56,
              height: 56,
              borderRadius: 15,
              backgroundColor: NARANJA,
              marginRight: 18,
            }}
          >
            <svg
              width={32}
              height={32}
              viewBox={TF_MARK_VIEWBOX}
              fill="none"
              stroke={FONDO}
              strokeWidth={TF_MARK_STROKE}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              {TF_MARK_PATHS.map((d) => (
                <path key={d} d={d} />
              ))}
            </svg>
          </div>
          <div style={{ display: "flex", fontSize: 34, fontWeight: 700, color: TINTA, letterSpacing: "-0.02em" }}>
            {SITE_NAME}
          </div>
        </div>
        {/* Rótulo en versal gris, como el KICKER de la superficie pública. */}
        <div
          style={{
            display: "flex",
            fontSize: 22,
            fontWeight: 600,
            color: GRIS,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
          }}
        >
          Licitación pública · TI
        </div>
      </div>

      {/* Anuncio */}
      <div style={{ display: "flex", flexDirection: "column" }}>
        <div
          style={{
            display: "flex",
            fontSize: titulo && titulo.length > 70 ? 44 : 52,
            fontWeight: 700,
            color: TINTA,
            lineHeight: 1.18,
            letterSpacing: "-0.02em",
            maxWidth: 1040,
          }}
        >
          {titulo ?? "Licitaciones públicas de tecnología en España"}
        </div>
        {organo && (
          <div style={{ display: "flex", fontSize: 28, color: GRIS, marginTop: 22, maxWidth: 1000 }}>{organo}</div>
        )}
      </div>

      {/* Datos clave del anuncio */}
      <div style={{ display: "flex", alignItems: "center" }}>
        {chips.length > 0 ? (
          chips.map((chip) => <Chip key={chip} texto={chip} />)
        ) : (
          <div style={{ display: "flex", fontSize: 26, color: GRIS }}>
            Radar de licitaciones TI del sector público español
          </div>
        )}
      </div>
    </div>,
    size,
  );
}
