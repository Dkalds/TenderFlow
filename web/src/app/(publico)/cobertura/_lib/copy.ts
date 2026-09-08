import type { SeccionEvidencia } from "../../_components/pagina-evidencia";

/**
 * Todo el texto que `/cobertura` escribe por su cuenta.
 *
 * Vive en un módulo aparte por dos motivos, y ninguno es el tamaño del fichero.
 *
 * El primero es que la mitad de esta página **ya no es copy**: las fuentes, sus
 * estados y lo que queda fuera del producto llegan de
 * `GET /api/v1/publico/cobertura`. Separar lo que se escribe de lo que se lee
 * deja a la vista cuál de las dos mitades puede envejecer sin que nadie se
 * entere — la de aquí.
 *
 * El segundo es que el criterio de aceptación de T7 exige que este texto pase
 * `lib/legal-placeholder.ts`, el mismo predicado que impide desplegar un aviso
 * legal con un recordatorio dentro. Un objeto exportado se recorre entero desde
 * un test (`__tests__/copy.test.ts`); un JSX con las frases incrustadas, no.
 */

export const META = {
  title: "Cobertura de datos",
  description:
    "Fuentes declaradas, alcance de cada una, margen de frescura y lo que queda fuera del producto, con fecha.",
} as const;

export const CABECERA = {
  kicker: "Cobertura",
  titulo: "Qué entra en TenderFlow y qué queda fuera",
  introduccion:
    "La utilidad del análisis depende de declarar el universo. Estas son las fuentes, las reglas de entrada y los límites que delimitan cada cifra del producto.",
} as const;

export const SECCIONES: SeccionEvidencia[] = [
  {
    titulo: "Un mercado acotado, no toda la contratación pública",
    texto: [
      "TenderFlow incluye expedientes con señal de tecnología enterprise. El corte combina coincidencias del diccionario, el universo íntegro de servicios TI y software (CPV 48 y 72) de PLACSP y TED, y el clasificador que decide qué familia tecnológica lleva cada uno. Cada expediente conserva el motivo por el que entró.",
      "Ese alcance hace comparables el precio y la competencia dentro de un mercado concreto. Si el negocio principal es obra pública, sanidad o suministro general, el corpus no representa ese mercado.",
    ],
    puntos: [
      "El corpus público aplica además un umbral de contenido antes de publicar una ficha.",
      "Los expedientes terminales no ocupan la bandeja de oportunidades abiertas.",
      "Una empresa vigilada abre un carril específico para conservar sus adjudicaciones desde el alta.",
    ],
  },
  {
    titulo: "De dónde sale el dato",
    texto: [
      "La lista de fuentes que hay más abajo no está escrita en esta página. La sirve la API desde el mismo inventario que vigila la frescura de la ingesta, así que una fuente que cambie de estado cambia aquí sin que nadie reescriba un párrafo.",
      "Cada fuente declara su propio alcance y el margen de frescura que se le exige. Son universos distintos y no se suman: un feed autonómico de descubrimiento no es un censo del mercado, y esta página no lo presenta como si lo fuera.",
    ],
    puntos: [
      "Cada ficha pública enlaza al anuncio oficial y muestra su fecha de actualización.",
      "El dato no es tiempo real y debe contrastarse con el perfil del contratante antes de presentar una oferta.",
      "La reutilización se declara conforme al marco explicado en el aviso legal.",
    ],
  },
  {
    titulo: "Calidad visible",
    texto: [
      // Ojo al reescribir esto: `lib/legal-placeholder.ts` busca sus frases por
      // subcadena, y la versión anterior decía «evita rellenarlos», que contiene
      // «a rellenar» y hacía saltar el detector de texto de relleno sobre un
      // párrafo que dice justo lo contrario. El test de esta carpeta lo fija.
      "Las fuentes oficiales no siempre publican órgano, importe, CPV o documentos con la misma completitud. TenderFlow conserva los vacíos, mide su cobertura y no los tapa con estimaciones presentadas como hechos.",
    ],
    puntos: [
      "La señal tecnológica distingue título, clasificador y pliegos cuando están disponibles.",
      "Los pliegos se procesan por lotes; la interfaz dice que un pliego aún no se ha leído en vez de improvisar un resumen.",
      "Los agregados analíticos se calculan en backend sobre el universo declarado, no sobre la página visible.",
    ],
  },
];

/** Rótulos del bloque que pinta el inventario servido por la API. */
export const FUENTES = {
  titulo: "Fuentes declaradas",
  introduccion:
    "Cada fila sale del inventario de conectores. El identificador es el que aparece en una alerta de ingesta, así que sirve para hablar de una fuente concreta con soporte.",
  /**
   * La frase que la página escribe *en lugar* de un número agregado.
   *
   * Está aquí y no en un comentario porque el lector merece saber por qué no
   * hay una cifra grande: la regla dura de `docs/regional-source-coverage.md`
   * es que estos feeds nunca se suman como cuota de mercado ni como censo.
   */
  sinCuota:
    "No hay aquí ninguna cuota de mercado, y su ausencia es la decisión: cada fuente cubre un universo distinto, y sumarlas daría un número con aspecto de censo que no lo es.",
  identificador: "Identificador de ingesta",
  frescuraPrefijo: "Se declara atrasada tras",
  frescuraSufijo: "horas sin una ingesta correcta.",
} as const;

/** Cómo se lee cada estado. La etiqueta es corta; la glosa explica qué implica. */
export const ESTADOS = {
  activa: {
    etiqueta: "Activa",
    glosa: "Se ingiere en cada pasada y su silencio genera una alerta.",
  },
  opcional: {
    etiqueta: "Opcional",
    glosa:
      "Puede estar apagada de forma legítima: le falta su configuración o no tiene nada que vigilar.",
  },
  fuera_de_alcance: {
    etiqueta: "Fuera de alcance",
    glosa: "Declarada fuera del producto: ni se ingiere ni se vigila.",
  },
} as const;

/** Rótulos del bloque de exclusiones. El contenido lo declara el backend. */
export const EXCLUSIONES = {
  titulo: "Fuera de alcance declarado",
  introduccion:
    "Lo siguiente no se ingiere, no se cuenta y no aparece en ninguna cifra del producto. Se declara con fecha para que «fuera de alcance» no se lea como «aún no hemos llegado».",
  decision: "Decisión",
  desde: "Declarado el",
} as const;

/** Lo que la página dice cuando la API no le pudo dar el inventario. */
export const SIN_INVENTARIO =
  "El inventario de fuentes no se pudo leer al generar esta página. No se muestra una lista incompleta.";
