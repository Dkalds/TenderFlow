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

/**
 * Destino del CTA "Solicita acceso".
 *
 * Con email configurado: `mailto:` con asunto y cuerpo prellenados (los dos
 * datos que el operador necesita para habilitar el acceso: email o dominio).
 * Sin él: /login como hasta ahora, con atribución UTM — Vercel Analytics ya
 * está montado y `utm_content` es una de sus dimensiones, así que distinguir
 * qué CTA convierte no requiere ni una línea de JavaScript en la landing.
 * El canonical de /login colapsa las variantes, así que el SEO no se entera.
 */
export function solicitarAccesoHref(utmContent: string): string {
  if (!CONTACT_EMAIL) {
    return `/login?utm_source=publico&utm_content=${encodeURIComponent(utmContent)}`;
  }
  const asunto = "Solicitud de acceso a TenderFlow";
  const cuerpo =
    "Hola,\n\n" + "Quiero solicitar acceso a TenderFlow.\n\n" + "Empresa:\n" + "Email o dominio a habilitar:\n";
  return `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(asunto)}&body=${encodeURIComponent(cuerpo)}`;
}
