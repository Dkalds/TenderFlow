import { esValorLegalPlaceholder } from "./legal-placeholder";

/**
 * Identidad del responsable del tratamiento.
 *
 * El aviso legal publicado terminaba con un recuadro que decía, literalmente,
 * «Pendiente de completar: identificación del responsable del tratamiento y
 * domicilio social». Es honesto y no sustituye al dato: el sitio está
 * publicado, es indexable y recoge una dirección de correo por consentimiento
 * explícito, así que el RGPD (art. 13) y la LSSI-CE (art. 10) exigen que quien
 * responde por ese tratamiento esté identificado **en el momento de la
 * recogida**.
 *
 * Los valores llegan por entorno y no van escritos en el árbol por el mismo
 * criterio que `CONTACT_EMAIL` (ADR-014: sin hardcode de lo que el entorno debe
 * proveer) y por uno más concreto: son datos societarios reales que no le
 * corresponde inventar a nadie que toque este fichero.
 *
 * Que falten no es un caso a tolerar en producción — `next.config.ts` rompe el
 * build de producción si no están—, pero sí en local y en el job `frontend` de
 * CI, que compila a propósito sin entorno. Por eso el módulo degrada en vez de
 * lanzar: la página dice qué falta en vez de mentir o de caerse.
 *
 * **Un valor de relleno cuenta como ausente**, y no es una sutileza: el guard
 * del build sólo miraba que la variable no estuviera vacía, así que producción
 * llegó a publicar «PLACEHOLDER LOCAL - NO DESPLEGAR» como responsable del
 * tratamiento. Un aviso legal con un recordatorio dentro no identifica a nadie,
 * y es peor que uno que declara la laguna: el primero aparenta cumplir. Ver
 * `lib/legal-placeholder.ts`.
 */

/**
 * Valor publicable, o `null`.
 *
 * `null` significa «no hay dato que publicar», y cubre por igual la variable sin
 * definir y la definida con un relleno: para el visitante que necesita saber
 * quién responde por sus datos, las dos son lo mismo.
 */
function valorLegal(bruto: string | undefined): string | null {
  return esValorLegalPlaceholder(bruto) ? null : (bruto as string).trim();
}

/** Razón social o nombre del responsable. `null` si el entorno no lo define. */
export const LEGAL_RESPONSABLE: string | null = valorLegal(process.env.NEXT_PUBLIC_LEGAL_RESPONSABLE);

/** NIF/CIF del responsable. */
export const LEGAL_NIF: string | null = valorLegal(process.env.NEXT_PUBLIC_LEGAL_NIF);

/** Domicilio a efectos de notificaciones. */
export const LEGAL_DOMICILIO: string | null = valorLegal(process.env.NEXT_PUBLIC_LEGAL_DOMICILIO);

/**
 * Meses que se conservan las solicitudes de acceso antes del borrado automático.
 *
 * El aviso decía «hoy no existe un borrado automático por plazo», que era
 * cierto y es justo lo que el RGPD pide fijar. El job lo aplica de verdad
 * (`scheduler/retention.py`); esta constante es la que se publica, y las dos
 * leen el mismo default para que no puedan divergir en silencio.
 */
export const LEGAL_MESES_RETENCION_SOLICITUDES = 24;

/** ¿Está completa la identificación que exige el RGPD? */
export function identificacionCompleta(): boolean {
  return Boolean(LEGAL_RESPONSABLE && LEGAL_NIF && LEGAL_DOMICILIO);
}

/**
 * Qué falta por publicar, en lenguaje llano y solo lo que falta de verdad.
 *
 * El recuadro anterior enumeraba siempre las mismas tres cosas aunque alguna
 * estuviera resuelta: un aviso que no distingue lo pendiente de lo hecho deja
 * de leerse.
 */
export function lagunasLegales(): string[] {
  const faltan: string[] = [];
  if (!LEGAL_RESPONSABLE) faltan.push("identificación del responsable del tratamiento");
  if (!LEGAL_NIF) faltan.push("NIF del responsable");
  if (!LEGAL_DOMICILIO) faltan.push("domicilio social");
  return faltan;
}
