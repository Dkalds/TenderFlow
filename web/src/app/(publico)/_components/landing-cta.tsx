import { ArrowRight } from "lucide-react";
import { solicitarAccesoHref } from "@/lib/contacto";
import { CONTENIDO } from "../_content/landing";
import { EnlaceSolicitarAcceso } from "./enlace-solicitar-acceso";
import { CTA_PRIMARIO } from "./landing-piel";

/* CTA de acceso. El destino lo decide `solicitarAccesoHref` (lib/contacto) y
 * hoy es siempre el ancla del formulario de esta misma página: sus dos
 * versiones anteriores —un `mailto:` dependiente de una variable de entorno, y
 * /login como fallback— no llevaban a ninguna parte utilizable.
 *
 * El ancla la pinta la isla `EnlaceSolicitarAcceso` para emitir el evento de
 * analytics del clic. Ojo con lo que ese evento mide: **intención, no
 * conversión**. Desde que el destino es un fragmento, pulsar el botón es un
 * scroll, no un envío. La conversión la reporta la página de gracias
 * (`solicitud-recibida`), que es la única que sabe si el POST prosperó; las
 * dos métricas juntas son las que dan el embudo. `utmContent` distingue de qué
 * CTA vino el clic — header, hero, intermedio— y por eso hay más de uno. */
export function CtaAcceso({ utmContent }: { utmContent: string }) {
  return (
    <EnlaceSolicitarAcceso href={solicitarAccesoHref()} ubicacion={utmContent} className={CTA_PRIMARIO}>
      {CONTENIDO.ctaPrimario}
      <ArrowRight
        className="h-4 w-4 transition-transform duration-200 ease-out group-hover:translate-x-0.5"
        aria-hidden="true"
      />
    </EnlaceSolicitarAcceso>
  );
}
