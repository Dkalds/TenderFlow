/**
 * Texto de la landing pública, como dato y no como JSX.
 *
 * Está separado del componente por dos razones. La primera es que el copy de
 * una landing se reescribe muchas más veces que su maquetación, y así una
 * revisión de texto no toca ni una línea de layout. La segunda es que el mismo
 * objeto alimenta el `<h1>`, los metadatos de la página y el JSON-LD de
 * `FAQPage`: si las preguntas visibles y las marcadas para Google salieran de
 * sitios distintos acabarían divergiendo, y marcar como FAQ algo que no está en
 * la página es exactamente lo que Google penaliza.
 *
 * REGLA AL EDITAR: cada afirmación de este fichero tiene que poder rastrearse a
 * código de este repositorio. No hay métricas de clientes, ni cifras de ahorro,
 * ni precios, ni testimonios, y no es un descuido: no existen en el producto, y
 * una landing es una declaración pública de una empresa real. Si algo suena
 * bien pero no se puede señalar dónde está implementado, no entra.
 *
 * SEGUNDA REGLA, de 2026-09: **presupuesto**. La versión anterior pintaba 1.697
 * palabras y explicaba concentración HHI, cuantiles p10/p50/p90, CODICE,
 * cursores incrementales y embeddings; una pregunta sobre si uno puede crearse
 * una cuenta se respondía con cookies httpOnly, CSRF y TOTP. Todo era cierto y
 * casi nada era legible para quien decide si escribir, que es un responsable de
 * ofertas de un partner tecnológico. Esa profundidad no se ha borrado: se ha
 * mudado a las tres páginas de evidencia —/cobertura, /metodologia y
 * /seguridad—, que ahora sí se enlazan desde aquí.
 *
 * El presupuesto vigente es **1.119 palabras visibles y un titular de 56
 * caracteres**, medidos, no estimados. Son números altos para una landing de
 * consumo y deliberados para ésta: el producto se vende explicando qué mide y
 * qué no, y una portada de cuatro frases obligaría a prometer en vez de
 * demostrar. Lo que se recortó fue jerga y repetición, no argumento. Antes de
 * añadir un párrafo, mirá si su sitio es una de las tres páginas de evidencia.
 *
 * TERCERA: **una sola voz**. Se tutea al lector de principio a fin. El texto
 * anterior alternaba «si tu negocio» con «vuestros concursos» y «¿qué queréis
 * mirar?» en la misma pantalla.
 *
 * Ojo con el README al verificar: su tabla de características está
 * desactualizada —da TED por "pendiente de cablear" cuando
 * `.github/workflows/scrape-daily.yml` lo ejecuta en el cron, y ese cron corre
 * cada cuatro horas pese a llamarse "daily"—. La fuente de verdad es el código.
 */

/** Clave de icono. La iconografía es maquetación, no contenido, pero la
 * correspondencia sí es del contenido: antes vivía en arrays paralelos
 * indexados por posición, de modo que reordenar este fichero desalineaba los
 * iconos sin un solo error de compilación —y un `?? ICONOS[0]` enmascaraba el
 * desajuste en vez de delatarlo—. Con una clave, el mapa del componente es
 * exhaustivo y el compilador avisa. */
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

export const CONTENIDO: ContenidoLanding = {
  // La marca no va delante: "TenderFlow" no tiene volumen de búsqueda y gastaría
  // los caracteres de más peso. La página usa `title.absolute`, así que este
  // título llega tal cual al resultado de búsqueda, sin el sufijo de la
  // plantilla del layout raíz.
  metaTitle: "Licitaciones TI del sector público: decidir dónde pujar",
  metaDescription:
    "Radar de licitaciones públicas de tecnología enterprise en España: scoring " +
    "de oportunidad, baja de referencia por segmento y competencia por órgano.",

  eyebrow: "Licitaciones de tecnología · Sector público español",

  // 56 caracteres. El anterior tenía 88 y ocupaba tres renglones del hero.
  // Conserva la keyword de búsqueda y las tres decisiones, que son la promesa
  // entera del producto.
  h1: "Licitaciones TI: dónde pujar, a qué precio, contra quién",
  // Nombra al destinatario con las familias que el clasificador reconoce de
  // verdad (ver `familias`) en vez de volver a describir el producto.
  subtitulo:
    "Un radar de concursos públicos de tecnología en España, para equipos que " +
    "venden SAP, Salesforce, Microsoft o ServiceNow a la administración.",

  // Descalificar arriba es un favor: quien no encaja se ahorra la página entera,
  // y nosotros una solicitud que no se podría atender.
  heroAcotacion: "Si vendes obra pública, sanidad o suministros generales, esto no te sirve.",

  // El alta self-service está desactivada en producción: `ALLOW_SELF_REGISTRATION`
  // es `False` por defecto y no se declara en `render.yaml`, así que
  // `POST /auth/register` responde 403; y el login con Google es fail-closed sin
  // allowlist. Un "crea tu cuenta gratis" sería una promesa que acaba en error.
  ctaPrimario: "Solicita acceso",
  ctaSecundario: "Cómo funciona",

  notaFuentes: "Fuentes oficiales: PLACSP cada cuatro horas, TED y los canales de Galicia y Euskadi.",

  ultimosTitulo: "Últimos anuncios publicados",
  ultimosFecha: "El más reciente:",
  ultimosEnlace: "Ver todos los anuncios publicados",

  ctaIntermedioTitulo: "¿Te sirve para tus concursos?",
  ctaIntermedioTexto: "No hace falta llegar al final de la página para pedir acceso.",

  publicoCierreTitulo: "Esto es solo la parte pública",
  publicoCierreTexto:
    "Aquí está el anuncio tal y como lo publica la fuente. Dentro, cada expediente " +
    "llega con su score de oportunidad, la baja de referencia de su segmento y quién " +
    "se lleva normalmente ese tipo de contrato.",

  pilaresKicker: "Cómo funciona",
  pilaresTitulo: "Tres decisiones sobre un mismo mercado",
  pilares: [
    {
      titulo: "Dónde pujar",
      icono: "radar",
      texto:
        "Cada día, los concursos abiertos ordenados por lo que encajan contigo: " +
        "importe, plazo, competencia esperada, margen, afinidad y señal técnica. " +
        "Los pesos son tuyos, y lo que descartas no vuelve a aparecer.",
    },
    {
      titulo: "A qué precio",
      icono: "precio",
      texto:
        "Cuánto se baja habitualmente en ese tipo de contrato, por empresa, órgano, " +
        "código CPV y comunidad autónoma, con escenarios cuando hay adjudicaciones " +
        "comparables suficientes para sostenerlos.",
    },
    {
      titulo: "Contra quién",
      icono: "competencia",
      texto:
        "Quién se lleva normalmente estos contratos y con qué cuota, con las uniones " +
        "temporales resueltas, y qué publica cada órgano de contratación y con qué " +
        "resultado.",
    },
  ],

  // Única enumeración de las trece familias en toda la página.
  familiasTitulo:
    "Solo entra el expediente con señal de tecnología enterprise: trece familias de " +
    "producto, más los servicios TI y software (CPV 48 y 72) de PLACSP y TED.",
  familias: [
    "SAP",
    "Salesforce",
    "Oracle",
    "Microsoft",
    "ServiceNow",
    "Workday",
    "IBM",
    "OpenText",
    "Unit4",
    "Meta4",
    "Sopra",
    "Sage",
    "Infor",
  ],

  capturaTitulo: "La bandeja de cada mañana",
  capturaTexto:
    "El triaje diario: los expedientes abiertos ordenados por score, con su banda, el " +
    "órgano, el importe y los días que quedan. A la derecha, de dónde sale la " +
    "puntuación de cada uno.",
  capturaAlt:
    "Radar de TenderFlow: bandeja de triaje ordenada por score, con banda, órgano, " +
    "tecnología, importe y plazo por expediente, y el panel de detalle con el " +
    "desglose de las seis dimensiones que componen la puntuación.",
  capturaEtiqueta: "radar · triaje diario",
  capturaNota: "Interfaz real del producto. Los expedientes de la imagen son datos de demostración.",

  franjaExpedientes: "Expedientes publicables ahora mismo",
  franjaComunidades: "Comunidades autónomas con índice propio",
  franjaCpv: "Códigos CPV con volumen suficiente",
  franjaActualizado: "Último expediente incorporado",
  franjaNota:
    "Cifras del corpus público, servidas por la API al generar esta página. No es " +
    "toda la contratación pública: es lo que ha entrado en el radar tecnológico y " +
    "supera el umbral de contenido para publicarse.",

  // Tres secciones, no siete. Cada una responde a una pregunta que un comprador
  // hace de verdad, y termina donde está la respuesta larga.
  secciones: [
    {
      kicker: "Qué entra",
      icono: "corpus",
      h2: "Un radar tecnológico, no un censo de toda la contratación pública",
      parrafos: [
        "Solo entra el expediente con señal de tecnología enterprise, marcado con el motivo por el que entró. Comparar precios y competencia exige un mercado acotado: en un índice general esas comparaciones no significan nada.",
        "La fuente principal es la Plataforma de Contratación del Sector Público, que se consulta cada cuatro horas; TED y los canales de Galicia y Euskadi añaden descubrimiento reciente, no histórico completo.",
      ],
      bullets: [
        "Datos de fuentes oficiales, reutilizados al amparo de la Ley 37/2007. No es tiempo real, y no sustituye a consultar la fuente antes de presentar una oferta.",
        "Lo que la fuente no publica queda vacío, y se mide cuánto falta en órgano de contratación, importe y CPV.",
        "Si vigilas una empresa se conservan sus adjudicaciones, aunque el expediente no dé señal tecnológica.",
      ],
      enlaces: [
        { texto: "Qué entra en el corpus y qué queda fuera", href: "/cobertura" },
        { texto: "Explora las licitaciones por código CPV", href: "/cpv" },
        { texto: "Ver los anuncios publicados, por comunidad autónoma", href: "/licitaciones" },
      ],
    },
    {
      kicker: "De dónde sale",
      icono: "scoring",
      h2: "Cada número dice de dónde sale, y cuándo no hay bastante para decirlo",
      parrafos: [
        "El orden del día se calcula sobre seis dimensiones y el desglose viaja con cada expediente: se ve qué aportó cada una y cuál no tenía dato. Una señal que falta puntúa neutral y se declara; no se disfraza de valoración negativa.",
        "Con la baja de referencia pasa lo mismo: hay escenarios cuando existen adjudicaciones comparables suficientes, y cuando no las hay el producto responde que la muestra es insuficiente.",
      ],
      bullets: [
        "Cuatro bandas —Caliente, Atractiva, Tibia y Descarte— para cortar el listado por umbral.",
        "El clasificador es auditable: la API devuelve qué términos pesaron en su decisión.",
        "Los escenarios son descriptivos: no devuelven probabilidad de ganar, y así está escrito en el código.",
      ],
      enlaces: [{ texto: "Cómo se calcula cada señal, y cuándo se declara insuficiente", href: "/metodologia" }],
    },
    {
      kicker: "Qué haces con ello",
      icono: "flujo",
      h2: "Del pliego al go/no-go, sin salir del expediente",
      parrafos: [
        "Un proceso nocturno lee los pliegos publicados, y con eso una licitación se resume al vuelo —objeto, importes, plazos, requisitos y riesgos— citando los fragmentos que ha usado. Lo que aún no está procesado se declara en vez de improvisarse.",
        "Las reglas de vigilancia se definen por palabra, CPV, importe y comunidad, con previsualización antes de guardarlas. Lo que decides trabajar pasa al tablero de oportunidades, con responsable, motivo de go/no-go y precio ofertado.",
      ],
      bullets: [
        "Renovaciones: contratos que vencen, con su riesgo de cambio de proveedor.",
        "API REST documentada, con claves de ámbito acotado que provisiona el operador.",
        "Tus datos son tuyos: exportables desde tu cuenta, y el borrado revoca sesiones y claves.",
      ],
      enlaces: [{ texto: "Controles de acceso y tratamiento de datos", href: "/seguridad" }],
    },
  ],

  faqKicker: "FAQ",
  faqTitulo: "Preguntas frecuentes",
  // Solo lo que el cuerpo de la página no responde, y en menos de sesenta
  // palabras cada una. Las dos últimas son las que todo comprador pregunta: que
  // la respuesta sea "no hay precio publicado" y "no hay plazo comprometido" no
  // es motivo para omitirlas — es la respuesta, y omitirla deja al visitante con
  // la pregunta encima en el momento de decidir si escribe.
  faq: [
    {
      pregunta: "¿Me dice la probabilidad de ganar un concurso?",
      respuesta:
        "No, y es una decisión de diseño. Lo que hay es comportamiento histórico: cuánto se ha bajado en adjudicaciones comparables y con qué dispersión. Cuando no hay casos resueltos suficientes para sostener esa lectura, el producto lo declara en vez de dar una cifra.",
    },
    {
      pregunta: "¿Puedo crearme una cuenta yo mismo?",
      respuesta:
        "Hoy no. El acceso es por invitación: se habilita tu email o el dominio de tu empresa y entras con Google. Por eso el botón principal es solicitar acceso y no crear una cuenta.",
    },
    {
      pregunta: "¿Qué pasa con mis datos y con lo que guardo dentro?",
      respuesta:
        "Los datos de mercado son comunes; tu perfil, tus reglas, tus favoritos y tus oportunidades quedan asociados a tu usuario y a tu organización. Puedes exportarlo todo y eliminar la cuenta desde tu propia pantalla de cuenta.",
    },
    {
      pregunta: "¿Cuánto cuesta?",
      respuesta:
        "No hay precio publicado. No existe alta self-service, ni pasarela de pago, ni planes: el acceso se concede uno a uno, y las condiciones se hablan en la conversación que abre la solicitud. Poner mientras tanto un «desde X €» sería inventarse el dato.",
    },
    {
      pregunta: "¿Cuánto tardáis en responder?",
      respuesta:
        "No hay plazo comprometido, porque ningún automatismo lo sostendría: la solicitud entra en una cola que revisa una persona, y el acceso se habilita a mano. Si tienes una fecha de presentación encima, dilo en el mensaje.",
    },
  ],

  explorarTitulo: "Explora los concursos publicados",
  explorarTexto:
    "Una parte del corpus es pública y no necesita cuenta: los anuncios ya " +
    "publicados, agrupados por comunidad autónoma y por código CPV.",
  explorar: [
    {
      titulo: "Por comunidad autónoma",
      texto: "Los anuncios publicados en cada comunidad, con su importe, plazo y estado.",
      href: "/licitaciones",
      icono: "corpus",
    },
    {
      titulo: "Por código CPV",
      texto: "El mismo corpus agrupado por el código de clasificación del contrato.",
      href: "/cpv",
      icono: "scoring",
    },
  ],

  cierreTitulo: "Compruébalo sobre tus propios concursos",
  cierreTexto:
    "Todo lo que hay en esta página se puede señalar en el código: de dónde vienen " +
    "los datos, cada cuánto entran, qué se filtra y qué no se calcula. Escribe y lo " +
    "vemos sobre los expedientes que te interesan.",
  cierreNota: "El acceso es por invitación.",

  responsablePrefijo: "Responsable del sitio:",

  formEmail: "Email de trabajo",
  formEmpresa: "Empresa",
  formMensaje: "¿Qué quieres mirar? (opcional)",
  formConsentimiento: "Acepto que TenderFlow guarde estos datos para responder a esta solicitud de acceso, según el",
  formAvisoLegal: "aviso legal",
  formEnviar: "Enviar solicitud",
  formTrampa: "No rellenes este campo",
};
