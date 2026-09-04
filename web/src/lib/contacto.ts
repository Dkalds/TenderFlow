/**
 * Canal de solicitud de acceso de la superficie pública.
 *
 * El acceso a TenderFlow es por invitación (`ALLOW_SELF_REGISTRATION` apagado
 * en producción), así que el CTA "Solicita acceso" necesita un destino real o
 * es un fondo de saco: /login solo deja entrar a quien ya tiene cuenta. La
 * dirección la pone el responsable vía entorno —ADR-014: sin hardcode que el
 * entorno debe proveer, y el aviso legal es explícito en que aquí no se
 * inventa un buzón que nadie lea—. Sin la variable, todo degrada al
 * comportamiento anterior (enlazar a /login) sin romper nada.
 *
 * Vive en su propio módulo, y no en `lib/site.ts`, porque lo importan también
 * componentes cliente (/login): así el bundle de cliente no arrastra la
 * resolución de `SITE_URL` y compañía.
 */

/** Email de contacto público, o `null` si el entorno no lo define. */
export const CONTACT_EMAIL: string | null = process.env.NEXT_PUBLIC_CONTACT_EMAIL?.trim() || null;

/** Ancla del formulario de solicitud en la landing. */
export const ANCLA_SOLICITUD = "solicitar-acceso";

/**
 * Destino del CTA "Solicita acceso".
 *
 * Apunta al formulario de la propia landing, que es el único destino que
 * funciona siempre: un `mailto:` no hace nada en un escritorio con webmail y
 * sin cliente de correo configurado, no deja rastro medible, y dependía de una
 * variable de entorno que si faltaba mandaba al visitante a /login, donde el
 * alta responde 403. El formulario persiste la petición en la API y devuelve
 * una página de gracias.
 *
 * Se devuelve con la barra inicial para que sirva igual desde /login, que está
 * en otra ruta; desde la propia landing el navegador lo trata como salto de
 * fragmento y no recarga nada.
 *
 * Sin parámetros. Tuvo uno, `utmContent`, que la función descartaba: desde que
 * el destino es un ancla de la propia página no hay navegación que etiquetar, y
 * quien distingue de qué CTA vino el clic es el evento de analytics de la isla
 * `EnlaceSolicitarAcceso`. Un argumento que se ignora invita a creer que la
 * atribución viaja en el enlace, que es justo lo que no pasa.
 *
 * El correo de contacto ya no decide el destino del CTA principal — se mantiene
 * para el pie y el aviso legal, donde sí es una dirección y no un embudo.
 */
export function solicitarAccesoHref(): string {
  return `/#${ANCLA_SOLICITUD}`;
}
