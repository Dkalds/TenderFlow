/**
 * F1.8 — glosario contextual: qué significa cada término del producto.
 *
 * El diccionario es **uno solo** y vive aquí. La consola ya tenía etiquetas
 * (`estados.ts`, `riesgos.ts`), pero una etiqueta no es una explicación:
 * «Evaluación» no le dice a nadie que ya no puede presentarse, y «baja» no
 * dice respecto a qué. Quien entra por primera vez a un producto de
 * contratación pública no vive en la Ley 9/2017.
 *
 * Qué NO está aquí, a propósito
 * -----------------------------
 * Los códigos de procedimiento, tramitación y tipo de contrato (F1.7). Esos
 * los sirve `GET /meta/filters` con su `descripcion`, porque son una lista
 * controlada de la fuente y copiarlos aquí rompería el invariante 3 de
 * `web/AGENTS.md` (sin hardcode que el backend debe proveer) y, sobre todo,
 * los dejaría envejeciendo en dos sitios. Use `glosarioDeOpcion()` para
 * convertir una opción del catálogo en una entrada de glosario y renderizarla
 * con el mismo componente.
 *
 * `test/glosario.test.ts` exige una entrada por cada estado de `estados.ts`:
 * un estado nuevo sin definición falla en CI, no en la pantalla.
 */

import { ESTADO_LABELS } from "@/lib/estados";

export interface EntradaGlosario {
  /** Cómo se titula la ayuda. Suele ser la etiqueta que el usuario ve. */
  termino: string;
  /** Una o dos frases. Sin jerga que a su vez necesite glosario. */
  definicion: string;
  /**
   * Ancla dentro de `/metodologia`. Sin ancla, el enlace lleva a la página
   * entera, que es peor pero no roto — nunca se omite el enlace.
   */
  ancla?: string;
}

/**
 * Estados de publicación. Las definiciones responden a la única pregunta que
 * el usuario tiene delante de la tabla: *¿puedo presentarme todavía?*
 */
const ESTADOS: Record<string, EntradaGlosario> = {
  PUB: {
    termino: "Publicada",
    definicion:
      "El anuncio está publicado y el plazo de presentación sigue abierto. Es donde se puede ofertar.",
    ancla: "estados",
  },
  EV: {
    termino: "Evaluación",
    definicion:
      "El plazo terminó y el órgano está valorando las ofertas recibidas. Ya no se puede presentar.",
    ancla: "estados",
  },
  RES: {
    termino: "Resuelta",
    definicion: "El procedimiento terminó con una resolución. No hay nada más que licitar.",
    ancla: "estados",
  },
  ADJ: {
    termino: "Adjudicada",
    definicion:
      "El contrato ya tiene adjudicatario. De aquí salen los datos de competencia y de baja.",
    ancla: "estados",
  },
  ANUL: {
    termino: "Anulada",
    definicion:
      "El órgano canceló el expediente antes de adjudicarlo, por desistimiento o por renuncia.",
    ancla: "estados",
  },
  PRE: {
    termino: "Anuncio previo",
    definicion:
      "Aviso de que el órgano piensa licitar algo. Todavía no hay pliego ni plazo al que presentarse.",
    ancla: "estados",
  },
  CREA: {
    termino: "Creada",
    definicion: "El expediente existe en la plataforma pero aún no se ha publicado la licitación.",
    ancla: "estados",
  },
  AGR: {
    termino: "Publicación agregada",
    definicion:
      "Un aviso que agrupa varios contratos ya celebrados. Nunca fue una oportunidad a la que presentarse.",
    ancla: "estados",
  },
  EJEC: {
    termino: "En ejecución",
    definicion: "El contrato está adjudicado y en marcha. Interesa por su fecha de fin, no por su plazo.",
    ancla: "estados",
  },
  CPM: {
    termino: "Consulta preliminar",
    definicion:
      "El órgano sondea al mercado antes de redactar el pliego. Participar no compromete a ofertar.",
    ancla: "estados",
  },
  OTROS: {
    termino: "Otros / sin clasificar",
    definicion:
      "Expedientes sin estado publicado, o con un código que la fuente emitió y aún no está catalogado.",
    ancla: "estados",
  },
};

/** Vocabulario del dominio que aparece en cabeceras, tarjetas y tooltips. */
const CONCEPTOS: Record<string, EntradaGlosario> = {
  baja: {
    termino: "Baja",
    definicion:
      "Cuánto por debajo del presupuesto de licitación se adjudicó, en porcentaje. Una baja del 20 % significa que el ganador cobró el 80 % del importe publicado.",
    ancla: "baja",
  },
  ute: {
    termino: "UTE",
    definicion:
      "Unión Temporal de Empresas: varias empresas se presentan juntas a un contrato y responden solidariamente. Se usa para llegar a una solvencia que ninguna alcanza sola.",
    ancla: "ute",
  },
  pyme: {
    termino: "PYME",
    definicion:
      "Pequeña o mediana empresa según la definición de la UE. Algunos contratos reservan lotes o dan puntos por serlo.",
    ancla: "pyme",
  },
  valor_estimado: {
    termino: "Valor estimado",
    definicion:
      "Todo lo que el órgano puede llegar a pagar: el presupuesto base más prórrogas y modificaciones previstas, sin IVA. Es mayor que el importe de licitación y es el que decide qué normas aplican.",
    ancla: "importes",
  },
  presupuesto_base: {
    termino: "Presupuesto base de licitación",
    definicion:
      "El importe máximo que se puede ofertar. Ofertar por encima excluye la propuesta.",
    ancla: "importes",
  },
  lote: {
    termino: "Lote",
    definicion:
      "Una parte del contrato que se adjudica por separado. Se puede ofertar a un lote sin ofertar a los demás, y cada uno tiene su importe y su ganador.",
    ancla: "lotes",
  },
  score: {
    termino: "Puntuación",
    definicion:
      "De 0 a 100, cuánto encaja una licitación con tu perfil, combinando importe, plazo, competencia esperada, margen y afinidad. No es una probabilidad de ganar.",
    ancla: "scoring",
  },
  temeridad: {
    termino: "Oferta anormalmente baja",
    definicion:
      "Oferta tan por debajo de las demás que el órgano exige justificarla antes de aceptarla. El pliego fija el umbral.",
    ancla: "baja",
  },
  organo: {
    termino: "Órgano de contratación",
    definicion:
      "Quien convoca y adjudica el contrato. No es lo mismo que el ministerio o la comunidad de la que depende.",
    ancla: "organos",
  },
  cpv: {
    termino: "CPV",
    definicion:
      "Vocabulario común de contratos públicos: el código de ocho dígitos que clasifica el objeto del contrato. Sus cuatro primeros dígitos agrupan por familia.",
    ancla: "cpv",
  },
  solvencia: {
    termino: "Solvencia",
    definicion:
      "Los mínimos económicos y técnicos que hay que acreditar para poder presentarse: facturación, contratos parecidos, titulaciones del equipo.",
    ancla: "solvencia",
  },
  deuc: {
    termino: "DEUC",
    definicion:
      "Documento Europeo Único de Contratación: la declaración responsable con la que se sustituye la documentación hasta que te proponen como adjudicatario.",
    ancla: "documentos",
  },
};

export const GLOSARIO: Record<string, EntradaGlosario> = { ...ESTADOS, ...CONCEPTOS };

/**
 * Entrada del glosario para un término, o `undefined` si no la hay.
 *
 * Acepta el código (`ADJ`) y la clave de concepto (`baja`), en cualquier caja:
 * los call-sites llegan desde datos de la API (códigos en mayúsculas) y desde
 * texto de la interfaz.
 */
export function glosario(clave: string | null | undefined): EntradaGlosario | undefined {
  if (!clave) return undefined;
  const limpia = clave.trim();
  return GLOSARIO[limpia] ?? GLOSARIO[limpia.toUpperCase()] ?? GLOSARIO[limpia.toLowerCase()];
}

/**
 * Convierte una opción de lista controlada de `GET /meta/filters` en una
 * entrada de glosario, para que procedimiento y tramitación (F1.7) usen el
 * mismo componente de ayuda sin que la consola guarde su propia copia del
 * vocabulario.
 */
export function glosarioDeOpcion(opcion: {
  etiqueta: string;
  descripcion: string;
}): EntradaGlosario {
  return { termino: opcion.etiqueta, definicion: opcion.descripcion, ancla: "procedimientos" };
}

/**
 * Los estados que `estados.ts` conoce y este glosario no sabe explicar.
 *
 * Es la comprobación que ejecuta el test: devuelve `[]` o falla. Se expone
 * como función y no se hace inline en el test para que cualquier pantalla
 * pueda afirmarlo también.
 */
export function estadosSinGlosario(): string[] {
  return Object.keys(ESTADO_LABELS).filter((codigo) => !(codigo in GLOSARIO));
}
