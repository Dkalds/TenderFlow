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
 * Cubre además los dos tratamientos que el sitio hace de datos de sus propios
 * visitantes, y que faltaban: el formulario de solicitud de acceso —cuya
 * casilla de consentimiento ya remitía aquí, a un documento que no describía
 * ningún tratamiento— y la medición de uso. Ambas secciones se escriben contra
 * el código: campos del formulario, sello de consentimiento del servidor,
 * estados de la cola, y qué recogen exactamente los eventos de analytics. Lo
 * que el código no hace —un borrado por plazo— no se promete; se declara como
 * pendiente en el recuadro del final, igual que el responsable del tratamiento.
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

      {/* Esta sección no existía y la casilla del formulario ya remitía aquí:
          "Acepto que TenderFlow guarde estos datos … según el aviso legal"
          apuntaba a un documento que no describía ningún tratamiento. El
          consentimiento es la base jurídica del único dato personal que este
          sitio recoge de sus visitantes, así que tiene que estar escrito.

          Cada afirmación es comprobable en el código: los campos son los del
          formulario (`_components/formulario-solicitud.tsx`), el sello de
          consentimiento lo pone el servidor (`db/solicitudes_acceso.py`), y los
          tres estados de la cola son los de `ESTADOS`. La conservación se
          describe como lo que hoy hace el código —no hay borrado automático— en
          vez de prometer un plazo que ningún job cumple. */}
      <h2 className="font-display mt-10 text-xl font-semibold tracking-[-0.02em]">
        Datos que nos facilitas al solicitar acceso
      </h2>
      <p className="text-muted-foreground mt-3 text-base leading-relaxed">
        El formulario de solicitud de acceso recoge tu dirección de correo electrónico y, si los rellenas, el nombre de
        tu empresa y un mensaje libre. Se registra también desde qué página se envió y la fecha y hora en que marcaste
        la casilla de consentimiento, que sella el servidor y no el navegador.
      </p>
      <p className="text-muted-foreground mt-3 text-base leading-relaxed">
        La <strong className="text-foreground">finalidad</strong> es única: atender esa solicitud y responderte. No se
        usan para enviarte comunicaciones comerciales, no se ceden a terceros y no alimentan ningún perfil. La{" "}
        <strong className="text-foreground">base jurídica</strong> es tu consentimiento explícito, que es lo que
        expresa esa casilla; sin marcarla el envío se rechaza y no se guarda nada.
      </p>
      <p className="text-muted-foreground mt-3 text-base leading-relaxed">
        La solicitud queda en una cola interna con tres estados —pendiente, atendida o descartada— que revisa una
        persona. Hoy no existe un borrado automático por plazo: se conserva mientras pueda hacer falta para gestionar
        la solicitud y hasta que pidas su supresión, que puedes hacer en cualquier momento por la dirección de contacto
        de más abajo. Puedes ejercer igualmente los derechos de acceso, rectificación, oposición, limitación y
        portabilidad que reconoce el Reglamento (UE) 2016/679, y retirar el consentimiento sin que ello afecte a la
        licitud del tratamiento anterior.
      </p>

      <h2 className="font-display mt-10 text-xl font-semibold tracking-[-0.02em]">Medición de uso</h2>
      <p className="text-muted-foreground mt-3 text-base leading-relaxed">
        Este sitio mide su propio uso con Vercel Analytics y Vercel Speed Insights: páginas vistas, rendimiento de
        carga y qué botón de solicitar acceso se pulsa. La medición es{" "}
        <strong className="text-foreground">sin cookies</strong> y no construye un identificador persistente de
        visitante, de modo que no requiere consentimiento previo ni banner. No se recoge ningún dato que te identifique
        y los eventos de solicitud registran únicamente desde qué punto de la página se pulsó, nunca lo que escribiste.
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
        social, y un plazo de conservación de las solicitudes de acceso respaldado por un borrado automático — hoy no
        hay ninguno, y por eso arriba se describe lo que el código hace en vez de prometer un plazo.
      </p>
      <p className="text-muted-foreground mt-6 text-sm">
        Última actualización de este aviso: agosto de 2026.
      </p>
    </article>
  );
}
