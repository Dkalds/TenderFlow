import type { Metadata } from "next";
import { SITE_NAME } from "@/lib/site";
import { CONTACT_EMAIL } from "@/lib/contacto";

/**
 * Aviso legal de la superficie pública.
 *
 * No es una página de relleno: la Ley 37/2007 permite reutilizar la
 * información del sector público, pero **condicionada** a citar la fuente, a
 * indicar la fecha de la última actualización y a no desnaturalizar el dato.
 * Las fichas cumplen las dos primeras condiciones cada una por su cuenta; esta
 * página es donde se declara el marco completo y se abre un canal de contacto.
 *
 * Va `noindex`: no aporta nada a un buscador y competiría por atención con las
 * páginas que sí. `follow` sí, para que el enlace del pie siga repartiendo
 * autoridad hacia el resto del sitio.
 */
export const metadata: Metadata = {
  title: "Aviso legal",
  description: `Origen de los datos, marco de reutilización y contacto de ${SITE_NAME}.`,
  robots: { index: false, follow: true },
  alternates: { canonical: "/aviso-legal" },
};

export default function AvisoLegal() {
  return (
    <article className="mx-auto w-full max-w-3xl px-6 py-14">
      <h1 className="font-display text-3xl font-bold tracking-[-0.025em] md:text-4xl">Aviso legal</h1>

      <h2 className="font-display mt-10 text-xl font-semibold tracking-[-0.02em]">Origen de los datos</h2>
      <p className="text-muted-foreground mt-3 text-base leading-relaxed">
        Las licitaciones que se publican en este sitio proceden de fuentes oficiales: la Plataforma de Contratación del
        Sector Público del Ministerio de Hacienda y la base de datos TED de la Unión Europea. Cada ficha indica su
        fuente, la fecha de la última actualización del dato y un enlace al anuncio original.
      </p>

      <h2 className="font-display mt-10 text-xl font-semibold tracking-[-0.02em]">Marco de reutilización</h2>
      <p className="text-muted-foreground mt-3 text-base leading-relaxed">
        La información se reutiliza al amparo de la Ley 37/2007, de 16 de noviembre, sobre reutilización de la
        información del sector público, y de su normativa de desarrollo. La reutilización no implica que las
        administraciones titulares de los datos participen en este sitio, lo respalden o lo revisen.
      </p>
      <p className="text-muted-foreground mt-3 text-base leading-relaxed">
        El contenido se ofrece sin alterar el sentido de la información original. Pueden existir desfases respecto a la
        fuente: el dato se actualiza de forma periódica, no en tiempo real.
      </p>

      <h2 className="font-display mt-10 text-xl font-semibold tracking-[-0.02em]">
        No sustituye al perfil del contratante
      </h2>
      <p className="text-muted-foreground mt-3 text-base leading-relaxed">
        Este sitio es una herramienta de análisis. Para preparar o presentar una oferta, los documentos válidos son
        exclusivamente los publicados en el perfil del contratante del órgano correspondiente, con sus plazos y
        condiciones. No asumimos responsabilidad por decisiones tomadas a partir de la información aquí mostrada.
      </p>

      <h2 className="font-display mt-10 text-xl font-semibold tracking-[-0.02em]">Datos de adjudicatarios</h2>
      <p className="text-muted-foreground mt-3 text-base leading-relaxed">
        Las páginas públicas de este sitio muestran únicamente el anuncio de licitación. No se publican datos de las
        empresas o personas adjudicatarias —ni su denominación, ni su número de identificación fiscal, ni los importes
        adjudicados—, porque un adjudicatario puede ser una persona física y su publicación indexada constituiría un
        tratamiento de datos personales sin base jurídica suficiente.
      </p>

      <h2 className="font-display mt-10 text-xl font-semibold tracking-[-0.02em]">Contacto</h2>
      <p className="text-muted-foreground mt-3 text-base leading-relaxed">
        Para solicitar la rectificación o la retirada de un contenido concreto de este sitio, escríbenos indicando el
        número de expediente afectado y el motivo. Atendemos las solicitudes relativas a datos personales conforme al
        Reglamento (UE) 2016/679.
      </p>

      {/* La dirección de contacto la pone el responsable vía
          NEXT_PUBLIC_CONTACT_EMAIL (lib/contacto): no se inventa aquí un buzón
          que nadie lea. Sin ella, el canal de ejercicio de derechos que exige
          el RGPD no existe de verdad, y el aviso lo dice en vez de callar. */}
      {CONTACT_EMAIL ? (
        <p className="text-muted-foreground mt-3 text-base leading-relaxed">
          Dirección de contacto:{" "}
          <a
            href={`mailto:${CONTACT_EMAIL}`}
            className="text-foreground font-medium underline-offset-4 hover:underline"
          >
            {CONTACT_EMAIL}
          </a>
        </p>
      ) : null}
      <p className="border-border text-muted-foreground mt-6 rounded-lg border border-dashed p-4 text-sm">
        <strong className="text-foreground">Pendiente de completar:</strong>{" "}
        {CONTACT_EMAIL ? "" : "dirección de contacto, "}identificación del responsable del tratamiento y domicilio
        social, antes de abrir el sitio al público.
      </p>
    </article>
  );
}
