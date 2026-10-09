/**
 * Formato de las cifras de Dirección, fuera de los componentes para probarlo
 * sin montar nada.
 *
 * **Presenta, no calcula** (ADR-014): el valor, el del periodo anterior, la
 * diferencia y hacia dónde es mejor (`mejor_si`) vienen hechos. Aquí sólo se
 * elige cómo se escribe cada unidad y de qué color va la diferencia.
 */
import type { Schemas } from "@/lib/api-types";
import { formatCompactCurrency, formatCurrency, formatNumber } from "@/lib/utils";

export type Tarjeta = Schemas["TarjetaMetrica"];
export type Corte = Schemas["CorteDireccion"];

/** La cifra con su unidad. `pct` llega como fracción 0-1. */
export function formatoCifra(unidad: Tarjeta["unidad"], valor: number): string {
  switch (unidad) {
    case "eur":
      return formatCurrency(valor);
    case "dias":
      return `${formatNumber(Math.round(valor))} días`;
    case "pct":
      return `${Math.round(valor * 100)} %`;
  }
}

/** La cifra corta, para la línea de comparación («frente a 50 k€»). */
function formatoCorto(unidad: Tarjeta["unidad"], valor: number): string {
  return unidad === "eur" ? formatCompactCurrency(valor) : formatoCifra(unidad, valor);
}

/** «+12 pp», «−350 k€», «−4 días». El signo va siempre, también en el cero. */
export function formatoDelta(unidad: Tarjeta["unidad"], delta: number): string {
  const signo = delta > 0 ? "+" : delta < 0 ? "−" : "±";
  const abs = Math.abs(delta);
  switch (unidad) {
    case "eur":
      return `${signo}${formatCompactCurrency(abs)}`;
    case "dias":
      return `${signo}${formatNumber(Math.round(abs))} días`;
    case "pct":
      return `${signo}${Math.round(abs * 100)} pp`;
  }
}

export type TonoDelta = "mejor" | "peor" | "igual";

/** Si la diferencia es buena o mala lo dice `mejor_si`, no la clave de la tarjeta. */
export function tonoDelta(tarjeta: Pick<Tarjeta, "delta" | "mejor_si">): TonoDelta | null {
  const delta = tarjeta.delta;
  if (delta == null) return null;
  if (delta === 0) return "igual";
  const sube = delta > 0;
  return sube === ((tarjeta.mejor_si ?? "sube") === "sube") ? "mejor" : "peor";
}

/**
 * La línea de comparación de una tarjeta, o `null` si no hay ninguna que
 * decir (sin ventana, la tarjeta no se compara).
 */
export function lineaComparacion(tarjeta: Tarjeta): string | null {
  if (tarjeta.depende_del_periodo === false) return "Foto de hoy: no depende del periodo.";
  if (tarjeta.n_anterior == null) return null;
  if (tarjeta.anterior == null) {
    return `Hace un año, sin base (n = ${formatNumber(tarjeta.n_anterior)}).`;
  }
  const frente = `frente a ${formatoCorto(tarjeta.unidad, tarjeta.anterior)} hace un año`;
  return tarjeta.delta != null ? `${formatoDelta(tarjeta.unidad, tarjeta.delta)} ${frente}` : frente;
}

/** `0,23–0,88` → «23–88 %». */
export function formatoIntervalo(bajo: number, alto: number): string {
  return `${Math.round(bajo * 100)}–${Math.round(alto * 100)} %`;
}

/**
 * Adónde lleva una fila de un corte: los registros que la sostienen. El órgano
 * abre su perfil en Mercado › Órganos; la tecnología, Mercado › Tecnologías
 * con el ámbito puesto. El tramo y el procedimiento no tienen destino propio.
 */
export function enlaceDeCorte(clave: Corte["clave"], valor: string): string | null {
  if (valor === "sin clasificar") return null;
  switch (clave) {
    case "organo":
      return `/mercado?vista=organos&organo_q=${encodeURIComponent(valor)}`;
    case "tecnologia":
      return `/mercado?vista=tecnologias&tecnologia=${encodeURIComponent(valor)}`;
    default:
      return null;
  }
}
