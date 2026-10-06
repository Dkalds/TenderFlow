import { plazoVisual, type BandaPlazo } from "@/components/pursuits/pursuit-presenters";
import type { LicitacionDetail } from "@/lib/licitacion-detail";

/**
 * Las fechas de un expediente, leídas para la ficha.
 *
 * Funciones puras —sin React— para poder probarlas con un «hoy» fijo: lo que
 * pintan depende del día en que se mire, y un test que dependiera del reloj
 * caducaría solo.
 */

const MS_DIA = 86_400_000;

function fechaValida(valor: string | null | undefined): Date | null {
  if (!valor) return null;
  const fecha = new Date(valor);
  return Number.isNaN(fecha.getTime()) ? null : fecha;
}

/**
 * Meses de ejecución entre inicio y fin, redondeados al mes más cercano.
 *
 * Es la misma información que las dos fechas, dicha en la unidad en que se
 * compara un contrato («24 meses»). Sin las dos fechas, o con el fin antes del
 * inicio, no hay duración que decir.
 */
export function mesesDeEjecucion(
  inicio: string | null | undefined,
  fin: string | null | undefined,
): number | null {
  const desde = fechaValida(inicio);
  const hasta = fechaValida(fin);
  if (!desde || !hasta) return null;
  const meses = Math.round((hasta.getTime() - desde.getTime()) / MS_DIA / 30.44);
  return meses >= 1 ? meses : null;
}

export type ClaveHito = "publicacion" | "hoy" | "limite" | "inicio" | "fin";

export interface Hito {
  clave: ClaveHito;
  etiqueta: string;
  fecha: Date;
  /** Ya ocurrió (o es hoy). */
  pasado: boolean;
  /** Solo en la fecha límite: la banda de la rampa de urgencia. */
  banda?: BandaPlazo;
  /** Solo en la fecha límite: «8 d para cierre», «Vencida hace 3 d». */
  plazo?: string;
}

const ETIQUETAS: Record<Exclude<ClaveHito, "hoy">, string> = {
  publicacion: "Publicación",
  limite: "Fecha límite",
  inicio: "Inicio",
  fin: "Fin",
};

/**
 * El calendario del expediente: publicación, fecha límite, inicio y fin, con
 * «hoy» colocado entre ellas para que se vea en qué punto está.
 *
 * Solo las fechas que el expediente publica: una que falta no se estima. Con
 * menos de dos fechas reales no hay calendario que dibujar y devuelve `[]`.
 */
export function hitosDelExpediente(
  licitacion: Pick<LicitacionDetail, "fecha_publicacion" | "fecha_limite" | "fecha_inicio" | "fecha_fin">,
  ahora: Date = new Date(),
): Hito[] {
  const fuentes: [Exclude<ClaveHito, "hoy">, string | null | undefined][] = [
    ["publicacion", licitacion.fecha_publicacion],
    ["limite", licitacion.fecha_limite],
    ["inicio", licitacion.fecha_inicio],
    ["fin", licitacion.fecha_fin],
  ];
  const reales: Hito[] = [];
  for (const [clave, valor] of fuentes) {
    const fecha = fechaValida(valor);
    if (!fecha) continue;
    const hito: Hito = { clave, etiqueta: ETIQUETAS[clave], fecha, pasado: fecha.getTime() <= ahora.getTime() };
    if (clave === "limite") {
      const plazo = plazoVisual(valor, ahora.getTime());
      if (plazo) {
        hito.banda = plazo.banda;
        hito.plazo = plazo.texto;
      }
    }
    reales.push(hito);
  }
  if (reales.length < 2) return [];

  const hoy: Hito = { clave: "hoy", etiqueta: "Hoy", fecha: ahora, pasado: true };
  // `sort` es estable: a igual instante, el hito real va antes que «hoy».
  return [...reales, hoy].sort((a, b) => a.fecha.getTime() - b.fecha.getTime());
}
