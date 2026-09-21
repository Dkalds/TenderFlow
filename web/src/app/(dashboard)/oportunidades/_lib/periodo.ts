/**
 * El periodo de la vista Rendimiento, fuera del componente para poder probarlo
 * sin montar nada.
 *
 * `GET /pursuits/metrics` acepta `period_from`/`period_to` y ninguna pantalla
 * los usaba: el embudo hablaba siempre del histórico completo, así que «cómo
 * vamos este año» no se podía responder. Aquí sólo se traduce una elección
 * («12 meses») a la ventana que se le pide al backend; **el recorte lo hace
 * él**, sobre el dataset entero (ADR-014).
 *
 * Las fechas se truncan al día en UTC a propósito. La ventana entra en la
 * `queryKey`, y una marca de tiempo al milisegundo cambiaría la clave en cada
 * render: React Query pediría otra vez, para siempre. Al día, la clave es
 * estable mientras dure la sesión y la respuesta se cachea.
 */

export type PeriodoClave = "12m" | "anio" | "historico";

export const PERIODOS = [
  { clave: "12m", label: "12 meses" },
  { clave: "anio", label: "Este año" },
  { clave: "historico", label: "Histórico" },
] as const satisfies readonly { clave: PeriodoClave; label: string }[];

/**
 * El histórico completo es el que había antes de que existiera el selector, y
 * sigue siendo la entrada: cambiar el universo por defecto cambiaría todas las
 * cifras de la pantalla sin que nadie lo pidiera.
 */
export const PERIODO_POR_DEFECTO: PeriodoClave = "historico";

/** `?periodo=` → clave conocida; cualquier otra cosa cae al histórico. */
export function periodoDeUrl(valor: string | null | undefined): PeriodoClave {
  return PERIODOS.some((periodo) => periodo.clave === valor)
    ? (valor as PeriodoClave)
    : PERIODO_POR_DEFECTO;
}

export interface RangoPeriodo {
  /** `period_from` en ISO, o `null` para no acotar por abajo. */
  desde: string | null;
  /** `period_to` en ISO, o `null` para no acotar por arriba. */
  hasta: string | null;
}

function inicioDelDiaUtc(año: number, mes: number, dia: number): string {
  return new Date(Date.UTC(año, mes, dia)).toISOString();
}

/**
 * La ventana que se le pide al backend.
 *
 * `hasta` va siempre a `null`: el extremo de arriba es «ahora», y fijarlo al
 * inicio del día de hoy dejaría fuera lo que ha pasado esta mañana.
 */
export function rangoDePeriodo(clave: PeriodoClave, ahora: Date): RangoPeriodo {
  const año = ahora.getUTCFullYear();
  const mes = ahora.getUTCMonth();
  const dia = ahora.getUTCDate();
  switch (clave) {
    case "12m":
      // `Date.UTC` normaliza el mes negativo, así que restar doce meses no
      // necesita aritmética de años aparte.
      return { desde: inicioDelDiaUtc(año, mes - 12, dia), hasta: null };
    case "anio":
      return { desde: inicioDelDiaUtc(año, 0, 1), hasta: null };
    case "historico":
      return { desde: null, hasta: null };
  }
}

/** El rótulo del universo, para que la pantalla diga de qué habla. */
export function etiquetaPeriodo(clave: PeriodoClave): string {
  switch (clave) {
    case "12m":
      return "Últimos 12 meses";
    case "anio":
      return "Desde el 1 de enero";
    case "historico":
      return "Histórico completo de la organización activa";
  }
}
