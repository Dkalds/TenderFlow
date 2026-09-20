/**
 * Qué falta para salir de la fase en la que está la oportunidad.
 *
 * Es el «path» del diseño: en vez de decir solo en qué fase está, dice qué
 * queda para pasar a la siguiente. Cada paso comprueba un **dato real** —de la
 * propia oportunidad, del kit de presentación o del contraste del pliego, que
 * el backend ya calcula—; una lista de pasos que se marcan en el cliente sería
 * estado de usuario fabricado en el frontend, que es justo lo que prohíben
 * ADR-014 y `docs/frontend-data-invariants.md`.
 *
 * Un paso `requerido` es de los que el backend exige para la transición
 * (`services/pursuits.py`): sin él, el PATCH se rechaza, así que la acción se
 * ofrece deshabilitada y diciendo qué falta. Los demás preparan la fase pero no
 * bloquean: el equipo decide si avanza igual.
 *
 * `hecho: null` es «no se sabe», y no «no»: el dato que lo decide todavía no ha
 * llegado o el pliego no lo trae. No cuenta como hecho ni se presenta como
 * pendiente.
 *
 * **Un hueco no se cierra por avanzar**: lo que quedó pendiente en una fase
 * anterior se arrastra a la lista, y se dice de dónde viene. Una oportunidad
 * que llega a «Preparando oferta» sin responsable sigue estando incompleta, y
 * esconderlo porque ya pasó esa fase es lo que hace que no se arregle nunca.
 * Se arrastran solo los pendientes de verdad (`hecho === false`), nunca los que
 * están sin dato, y cada paso se identifica por el campo del contrato del que
 * sale, así que un mismo campo no aparece dos veces con dos nombres.
 */

import { statusLabel } from "@/components/pursuits/pursuit-presenters";
import { esTerminal, type Pursuit, type PursuitStatus } from "@/hooks/use-pursuits";
import { motivoBloqueo, siguienteFase } from "./flujo";

export interface PasoSalida {
  /** El campo del contrato del que sale, que es también su identidad. */
  clave: string;
  texto: string;
  /** `true` hecho, `false` pendiente, `null` sin dato para decidirlo. */
  hecho: boolean | null;
  /** Lo exige el backend para la transición; sin él no se ofrece avanzar. */
  requerido?: boolean;
  /** Una línea con el porqué, cuando el dato lo tiene. */
  detalle?: string;
}

export type AccionSalida =
  | { tipo: "avanzar"; destino: PursuitStatus; etiqueta: string; bloqueo: string | null }
  | { tipo: "cerrar"; etiqueta: string };

export interface SalidaFase {
  titulo: string;
  pasos: PasoSalida[];
  /** Pasos con dato suficiente para darlos por hechos. */
  hechos: number;
  accion: AccionSalida | null;
  nota: string;
}

/** Lo que el kit y el contraste aportan, cuando ya han llegado. */
export interface ContextoSalida {
  kit?: { listos: number; total: number };
  contraste?: { total_requisitos: number; desconocido: number };
}

const NOTA_EVENTO = "Avanzar de fase escribe un evento en el historial, con quién y cuándo.";
const NOTA_CERRADA =
  "Una oportunidad cerrada ya no cambia de fase. Lo que falte se completa en «Todos los campos».";

function conTexto(valor: string | null | undefined): boolean {
  return Boolean(valor && valor.trim());
}

function pasoContraste(contraste: ContextoSalida["contraste"]): PasoSalida {
  const base = { clave: "contraste", texto: "Requisitos del pliego contrastados" };
  if (!contraste) return { ...base, hecho: null };
  if (contraste.total_requisitos === 0) {
    return { ...base, hecho: null, detalle: "El pliego no tiene requisitos extraídos" };
  }
  return {
    ...base,
    hecho: contraste.desconocido === 0,
    detalle:
      contraste.desconocido > 0
        ? `${contraste.desconocido} de ${contraste.total_requisitos} sin contrastar`
        : `${contraste.total_requisitos} requisitos con veredicto`,
  };
}

function pasoKit(kit: ContextoSalida["kit"]): PasoSalida {
  const base = { clave: "kit", texto: "Documentación del kit lista" };
  if (!kit) return { ...base, hecho: null };
  if (kit.total === 0) {
    return { ...base, hecho: null, detalle: "El pliego no tiene documentos extraídos" };
  }
  return { ...base, hecho: kit.listos === kit.total, detalle: `${kit.listos} de ${kit.total} listos` };
}

function pasosDeCierre(pursuit: Pursuit): PasoSalida[] {
  const pasos: PasoSalida[] = [
    {
      clave: "resultado",
      texto: `Resultado registrado: ${statusLabel(pursuit.status)}`,
      hecho: true,
    },
    {
      clave: "motivo",
      texto: "Motivo del cierre anotado",
      hecho: conTexto(pursuit.outcome_reason_code) || conTexto(pursuit.outcome_reason),
    },
  ];
  // Solo si se ganó: en una pérdida el importe es de otro y retirarla no
  // adjudica nada, así que pedirlo dejaría la ficha incompleta para siempre.
  if (pursuit.status === "won") {
    pasos.push({
      clave: "importe",
      texto: "Importe adjudicado anotado",
      hecho: pursuit.awarded_amount_eur != null,
    });
  }
  return pasos;
}

function pasosDeFase(fase: PursuitStatus, pursuit: Pursuit, contexto: ContextoSalida): PasoSalida[] {
  switch (fase) {
    case "identified":
      return [
        {
          clave: "responsable",
          texto: "Responsable asignado",
          hecho: pursuit.responsible_user_id != null,
        },
        {
          clave: "plazo",
          texto: "Fecha límite conocida",
          hecho: pursuit.tender_deadline != null,
        },
        {
          clave: "proxima",
          texto: "Próxima acción planificada",
          hecho: conTexto(pursuit.next_action),
        },
      ];
    case "qualifying":
      return [
        pasoContraste(contexto.contraste),
        {
          clave: "oferta",
          texto: "Oferta prevista estimada",
          hecho: pursuit.offer_price_eur != null,
        },
      ];
    case "go_no_go":
      // Con el NO-GO ya tomado, de esta fase no se avanza: se retira. Lo que
      // queda por comprobar es que el motivo esté escrito, que es lo que
      // sostiene la decisión en el historial.
      if (pursuit.decision === "no_go") {
        return [
          { clave: "decision", texto: "Decisión registrada: NO-GO", hecho: true },
          {
            clave: "motivo",
            texto: "Motivo de la decisión anotado",
            hecho: conTexto(pursuit.decision_reason),
          },
        ];
      }
      return [
        {
          clave: "oferta",
          texto: "Oferta prevista fijada",
          hecho: pursuit.offer_price_eur != null,
        },
        {
          clave: "decision",
          texto: "Decisión registrada: GO",
          hecho: pursuit.decision === "go",
          requerido: true,
        },
        {
          clave: "motivo",
          texto: "Motivo de la decisión anotado",
          hecho: conTexto(pursuit.decision_reason),
          requerido: true,
        },
      ];
    case "preparing":
      return [
        pasoKit(contexto.kit),
        {
          clave: "oferta",
          texto: "Precio de la oferta fijado",
          hecho: pursuit.offer_price_eur != null,
        },
      ];
    case "submitted":
      return [
        {
          clave: "proxima",
          texto: "Seguimiento de la mesa planificado",
          hecho: conTexto(pursuit.next_action),
        },
        {
          clave: "adjudicacion",
          texto: "Adjudicación publicada detectada",
          hecho: pursuit.adjudicacion != null,
          detalle:
            pursuit.adjudicacion == null
              ? "La ingesta todavía no ha visto la adjudicación de este expediente"
              : undefined,
        },
      ];
    default:
      return pasosDeCierre(pursuit);
  }
}

/** Las fases abiertas en orden: por ahí se mira atrás buscando huecos. */
const FASES_ABIERTAS: readonly PursuitStatus[] = [
  "identified",
  "qualifying",
  "go_no_go",
  "preparing",
  "submitted",
];

/**
 * Lo que quedó pendiente en las fases anteriores, con su procedencia.
 *
 * Solo lo pendiente de verdad: un paso sin dato (`null`) no se arrastra como
 * deuda, y lo que ya está en la lista de la fase actual no se repite. De una
 * cerrada no se arrastra nada: ahí ya no hay nada que preparar.
 */
function pasosArrastrados(
  pursuit: Pursuit,
  contexto: ContextoSalida,
  propios: PasoSalida[],
): PasoSalida[] {
  const hasta = FASES_ABIERTAS.indexOf(pursuit.status);
  if (hasta <= 0) return [];
  const vistos = new Set(propios.map((paso) => paso.clave));
  const arrastrados: PasoSalida[] = [];
  for (const fase of FASES_ABIERTAS.slice(0, hasta)) {
    for (const paso of pasosDeFase(fase, pursuit, contexto)) {
      if (paso.hecho !== false || vistos.has(paso.clave)) continue;
      vistos.add(paso.clave);
      arrastrados.push({
        ...paso,
        // Obligatorio lo es para su transición, no para ésta.
        requerido: false,
        detalle: `Quedó pendiente en «${statusLabel(fase)}»`,
      });
    }
  }
  return arrastrados;
}

const ETIQUETA_AVANCE: Record<string, string> = {
  identified: "Empezar a cualificar",
  qualifying: "Llevar a decisión",
  go_no_go: "Empezar la oferta",
  preparing: "Marcar presentada",
};

function accionDeFase(pursuit: Pursuit): AccionSalida | null {
  if (esTerminal(pursuit.status)) return null;
  if (pursuit.status === "submitted") {
    return { tipo: "cerrar", etiqueta: "Registrar resultado" };
  }
  if (pursuit.status === "go_no_go" && pursuit.decision === "no_go") {
    return { tipo: "cerrar", etiqueta: "Retirar la oportunidad" };
  }
  const destino = siguienteFase(pursuit.status);
  if (!destino) return null;
  return {
    tipo: "avanzar",
    destino,
    etiqueta: ETIQUETA_AVANCE[pursuit.status] ?? `Pasar a ${statusLabel(destino)}`,
    bloqueo: motivoBloqueo(pursuit, destino),
  };
}

export function salidaDeFase(pursuit: Pursuit, contexto: ContextoSalida = {}): SalidaFase {
  const propios = pasosDeFase(pursuit.status, pursuit, contexto);
  const pasos = [...propios, ...pasosArrastrados(pursuit, contexto, propios)];
  return {
    titulo: esTerminal(pursuit.status)
      ? "Lo que quedó registrado al cerrar"
      : `Para salir de «${statusLabel(pursuit.status)}»`,
    pasos,
    hechos: pasos.filter((paso) => paso.hecho === true).length,
    accion: accionDeFase(pursuit),
    nota: esTerminal(pursuit.status) ? NOTA_CERRADA : NOTA_EVENTO,
  };
}
