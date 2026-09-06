/**
 * Contrato del copy de la superficie pública: las formas, no el texto.
 *
 * Se separó de `landing.ts` en el reparto de 2026-09 y la frontera no es de
 * tamaño, es de oficio: aquí está lo que TypeScript verifica —qué campos
 * existen, cuáles son obligatorios y qué significa cada uno—, y al lado, en
 * `landing.ts`, el texto que se revisa y se reescribe. Una revisión de copy no
 * abre este fichero; añadir un bloque a la portada empieza por él.
 *
 * Los bloques de la portada (`_components/landing-*.tsx`) reciben estas formas
 * como props, así que son también el contrato entre el copy y la maquetación.
 */

/** Clave temática de cada bloque.
 *
 * Nació para elegir el icono de una tarjeta; el rediseño de 2026-09 retiró los
 * iconos de la portada y la clave se quedó por otro motivo: es lo que permite a
 * `page.tsx` reconocer una sección concreta —dónde va el diccionario de
 * familias, tras cuál el reclamo intermedio— sin comparar títulos, que cambian
 * en cada revisión de copy. Sigue siendo una clave y no una posición: reordenar
 * este fichero no descoloca nada. */
export type IconoLanding = "radar" | "precio" | "competencia" | "corpus" | "scoring" | "pliegos" | "flujo";

/** Los tres verbos del producto, arriba del todo. Cada uno resume una
 * consola real (Radar / baja de referencia / módulo competitivo); el detalle
 * verificable de cada afirmación vive en la sección correspondiente. */
export interface PilarLanding {
  titulo: string;
  texto: string;
  icono: IconoLanding;
}

/** Enlace interno hacia la superficie pública de datos o hacia una página de
 * evidencia. Además de útil para el lector, reparte autoridad interna. */
export interface EnlaceLanding {
  texto: string;
  href: string;
}

export interface SeccionLanding {
  /** Etiqueta corta de navegación visual ("Qué entra", "De dónde sale", …). */
  kicker: string;
  h2: string;
  parrafos: string[];
  bullets: string[];
  icono: IconoLanding;
  /** Vacío en las secciones que no tienen dónde seguir leyendo. */
  enlaces?: EnlaceLanding[];
}

export interface PreguntaLanding {
  pregunta: string;
  respuesta: string;
}

/** Tarjeta de la sección "Explorar". Vivía como JSX literal en `page.tsx`, que
 * es exactamente lo que este fichero existe para evitar. */
export interface ExplorarLanding {
  titulo: string;
  texto: string;
  href: string;
  icono: IconoLanding;
}

export interface ContenidoLanding {
  metaTitle: string;
  metaDescription: string;
  eyebrow: string;
  h1: string;
  subtitulo: string;
  /** A quién **no** le sirve, en el hero y no cuatro pantallas más abajo.
   *  En un producto deliberadamente estrecho, descalificar rápido es un favor
   *  al visitante y ahorra una solicitud que nadie va a poder atender. */
  heroAcotacion: string;
  ctaPrimario: string;
  ctaSecundario: string;
  notaFuentes: string;
  /** Rótulos del extracto de anuncios reales del hero. Dicen «publicados» y no
   *  «incorporados» porque el endpoint ordena por fecha de publicación: misma
   *  disciplina que las etiquetas de la franja. */
  ultimosTitulo: string;
  ultimosFecha: string;
  ultimosEnlace: string;
  /** Reclamo intermedio. El único punto de conversión estaba al final de la
   *  página: quien ya estaba convencido a mitad no tenía dónde actuar. */
  ctaIntermedioTitulo: string;
  ctaIntermedioTexto: string;
  /** Cierre de los hubs públicos, que son las páginas por las que se entra
   *  desde un buscador. Vive aquí, con el resto del copy de la superficie
   *  pública, aunque no se pinte en la portada. */
  publicoCierreTitulo: string;
  publicoCierreTexto: string;
  pilaresKicker: string;
  pilaresTitulo: string;
  pilares: PilarLanding[];
  familiasTitulo: string;
  familias: string[];
  /** Rótulos y alt de la única captura del producto. El alt va aquí y no en el
   *  TSX porque es copy: lo lee un lector de pantalla y lo indexa Google como
   *  cualquier otro texto. */
  capturaTitulo: string;
  capturaTexto: string;
  capturaAlt: string;
  capturaEtiqueta: string;
  /** No es opcional: la interfaz es real pero los expedientes de la imagen son
   *  de demostración, y presentarlos como reales rompería la regla de arriba. */
  capturaNota: string;
  /** Etiquetas de la franja de cifras. Los números los da el backend; lo único
   *  que se escribe aquí es cómo se llaman, y ahí está el riesgo: una etiqueta
   *  generosa convierte un agregado honesto en una cifra inflada. */
  franjaExpedientes: string;
  franjaComunidades: string;
  franjaCpv: string;
  /** Etiqueta de la fecha de frescura. Dice exactamente lo que el dato mide
   *  —cuándo entró el último expediente— y **no** "última sincronización": una
   *  pasada que no encuentra nada no mueve esa fecha, y llamarla sync sería
   *  afirmar que el pipeline corrió cuando el dato no lo demuestra. */
  franjaActualizado: string;
  franjaNota: string;
  secciones: SeccionLanding[];
  faqKicker: string;
  faqTitulo: string;
  faq: PreguntaLanding[];
  explorarTitulo: string;
  explorarTexto: string;
  explorar: ExplorarLanding[];
  cierreTitulo: string;
  cierreTexto: string;
  cierreNota: string;
  /** Quién responde por el sitio. El nombre sale de `lib/legal.ts` cuando el
   *  entorno lo define; el rótulo que lo acompaña vive aquí. Una página que
   *  pide el correo de alguien y no dice quién hay detrás pide más de lo que
   *  ofrece. */
  responsablePrefijo: string;
  /** Formulario de solicitud de acceso. Etiquetas y textos legales: es lo que
   *  lee quien decide dejar sus datos, así que es copy y vive aquí. */
  formEmail: string;
  formEmpresa: string;
  formMensaje: string;
  formConsentimiento: string;
  formAvisoLegal: string;
  formEnviar: string;
  /** Etiqueta del campo trampa. No la ve nadie salvo un bot o un lector de
   *  pantalla mal configurado; existe para que el campo no quede sin nombre. */
  formTrampa: string;
}
