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

/** Enlace interno hacia la superficie pública de datos. Además de útil para el
 * lector, reparte autoridad interna hacia los hubs indexables. */
export interface EnlaceLanding {
  texto: string;
  href: string;
}

export interface SeccionLanding {
  /** Etiqueta corta de navegación visual ("Corpus", "Scoring", …). */
  kicker: string;
  h2: string;
  parrafos: string[];
  bullets: string[];
  icono: IconoLanding;
  /** Vacío en las secciones que no hablan de algo visible sin cuenta. */
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
  ctaPrimario: string;
  ctaSecundario: string;
  notaFuentes: string;
  pilaresKicker: string;
  pilaresTitulo: string;
  pilares: PilarLanding[];
  familiasTitulo: string;
  familias: string[];
  /** Alt de la captura del hero. Va aquí y no en el TSX porque es copy: lo lee
   *  un lector de pantalla y lo indexa Google como cualquier otro texto. */
  capturaHeroAlt: string;
  capturaHeroEtiqueta: string;
  capturaKicker: string;
  capturaTitulo: string;
  capturaTexto: string;
  capturaAlt: string;
  capturaEtiqueta: string;
  /** No es opcional: la interfaz es real pero los expedientes de las imágenes
   *  son de demostración, y presentarlos como reales rompería la regla de
   *  arriba. Viaja con cada figura. */
  capturaNota: string;
  /** Etiquetas de la franja de cifras. Los números los da el backend; lo único
   *  que se escribe aquí es cómo se llaman, y ahí está el riesgo: una etiqueta
   *  generosa convierte un agregado honesto en una cifra inflada. */
  franjaExpedientes: string;
  franjaComunidades: string;
  franjaCpv: string;
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

  eyebrow: "Inteligencia de licitaciones · Tecnología enterprise · España",

  // El espacio duro en "a qué" evita que el corte de línea deje una "a"
  // huérfana a final de renglón en los anchos de hero más habituales.
  h1: "Licitaciones de tecnología del sector público: decide dónde pujar, a qué precio y contra quién",
  // El subtítulo repetía los tres verbos que el h1 acaba de decir y que las
  // tarjetas de abajo desarrollan: en pantalla y media la misma tríada salía
  // cuatro veces. Aquí se queda con lo que el h1 no dice — qué es y qué acota.
  subtitulo:
    "Un radar sectorial: solo los expedientes con señal de tecnología enterprise, " +
    "con el contexto que hace falta para decidir sobre ellos.",

  // El alta self-service está desactivada en producción: `ALLOW_SELF_REGISTRATION`
  // es `False` por defecto y no se declara en `render.yaml`, así que
  // `POST /auth/register` responde 403; y el login con Google es fail-closed sin
  // allowlist. Un "crea tu cuenta gratis" sería una promesa que acaba en error.
  ctaPrimario: "Solicita acceso",
  ctaSecundario: "Cómo funciona",

  notaFuentes:
    "Fuentes oficiales: PLACSP cada cuatro horas, TED y los RSS de Galicia y " + "Euskadi. Acceso por invitación.",

  pilaresKicker: "Cómo funciona",
  pilaresTitulo: "Tres decisiones sobre un mismo corpus acotado",
  pilares: [
    {
      titulo: "Dónde pujar",
      icono: "radar",
      texto:
        "Radar ordena la bandeja diaria por score de oportunidad sobre seis " +
        "dimensiones, con pesos configurables por usuario. Bandas Caliente, " +
        "Atractiva, Tibia y Descarte para cortar por umbral, y lo descartado " +
        "no vuelve a aparecer.",
    },
    {
      titulo: "A qué precio",
      icono: "precio",
      texto:
        "Baja media por empresa, órgano, CPV y comunidad autónoma; escenarios " +
        "por cuantiles sobre adjudicaciones comparables y un intervalo de baja " +
        "previsto p10/p50/p90 con su calibración declarada.",
    },
    {
      titulo: "Contra quién",
      icono: "competencia",
      texto:
        "Cuota y concentración HHI sobre las adjudicaciones oficiales, dossier " +
        "por competidor con NIF normalizado, alias y UTEs, e historial de lo " +
        "que publica cada órgano de contratación y con qué resultado.",
    },
  ],

  // Única enumeración de las trece familias en toda la página. Estaba repetida
  // en la franja, en la prosa de la primera sección y en una FAQ: tres sitios
  // que había que tocar a la vez para añadir una familia al diccionario.
  familiasTitulo:
    "Solo entra el expediente con señal de tecnología enterprise: trece familias " +
    "de producto en el diccionario, más rescate del clasificador sobre CPV 48 y 72.",
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

  capturaHeroAlt:
    "Radar de TenderFlow: bandeja de triaje ordenada por score, con banda, órgano, " +
    "tecnología, importe y plazo por expediente, y el panel de detalle con el " +
    "desglose de las seis dimensiones que componen la puntuación.",
  capturaHeroEtiqueta: "radar · triaje diario",
  capturaKicker: "Detalle",
  capturaTitulo: "El corpus entero, en una tabla",
  capturaTexto:
    "El Radar es la vista de trabajo diaria; debajo está el corpus completo con " +
    "todos los campos —expediente, órgano, importe, estado, score, fecha, CCAA, " +
    "CPV y tecnología—, ordenable por cualquiera de ellos y exportable.",
  capturaAlt:
    "Vista de detalle de TenderFlow: tabla del corpus con expediente, título, órgano, " +
    "importe, estado, score, fecha, comunidad autónoma, CPV y tecnología en columnas ordenables.",
  capturaEtiqueta: "detalle · corpus completo",
  capturaNota: "Interfaz real del producto. Los expedientes de la imagen son datos de demostración.",

  franjaExpedientes: "Expedientes publicables ahora mismo",
  franjaComunidades: "Comunidades autónomas con índice propio",
  franjaCpv: "Códigos CPV con volumen suficiente",
  franjaNota:
    "Cifras del corpus público, servidas por la API en el momento de generar esta " +
    "página. No es toda la contratación pública: es lo que ha entrado en el radar " +
    "tecnológico y supera el umbral de contenido para publicarse.",

  // Cuatro secciones, no siete. Las siete anteriores compartían plantilla exacta
  // —dos párrafos y tres bullets cada una— y ocupaban casi la mitad del scroll
  // repitiendo con más palabras lo que los pilares ya habían dicho en tres
  // tarjetas. Corpus y Fuentes eran el mismo tema partido en dos, igual que
  // Precio y Competencia, y que Pliegos y Flujo.
  secciones: [
    {
      kicker: "Corpus y fuentes",
      icono: "corpus",
      h2: "Un radar tecnológico, no un censo de toda la contratación pública",
      parrafos: [
        "TenderFlow no indexa toda la contratación pública española. Solo entra el expediente con señal de tecnología enterprise: coincidencia con el diccionario de familias, rescate del clasificador sobre CPV 48 y 72, o consulta directa por esos CPV en TED. Cada uno queda marcado con el motivo por el que entró. Comparar precios y competencia exige un mercado acotado; en un índice general esas comparaciones no significan nada. Si tu negocio es obra pública, sanidad o suministros generales, esto no te sirve.",
        "La fuente principal es el feed ATOM de la Plataforma de Contratación del Sector Público: cada cuatro horas, con cursor incremental e historial de cambios por expediente. Se suman TED y los RSS oficiales de Galicia y Euskadi, que son de descubrimiento reciente —no aportan histórico completo— y el producto no los presenta como si lo hicieran.",
      ],
      bullets: [
        "Datos de fuentes oficiales, reutilizados al amparo de la Ley 37/2007. No es tiempo real, y no sustituye a consultar la fuente oficial antes de presentar una oferta.",
        "Match por palabra completa sobre título y descripción; cada licitación conserva la versión del filtro y del clasificador con la que entró.",
        "Los campos que la fuente no publica quedan vacíos, y se mide el porcentaje de nulos en órgano de contratación, importe y CPV.",
        "Carril por NIF: si vigilas una empresa se conservan sus adjudicaciones aunque el expediente no dé señal tecnológica, desde que la das de alta.",
      ],
      enlaces: [
        { texto: "Explora las licitaciones por código CPV", href: "/cpv" },
        { texto: "Ver los anuncios publicados, por comunidad autónoma", href: "/licitaciones" },
      ],
    },
    {
      kicker: "Scoring",
      icono: "scoring",
      h2: "Decide a qué presentarte: scoring de oportunidad con tu propio perfil",
      parrafos: [
        "El ranking ordena el mercado abierto sobre seis dimensiones: importe, plazo, competencia esperada, margen, afinidad y señal técnica. Cada usuario guarda su perfil —pesos, keywords, CPV y rango de importe—; sin perfil se aplican los valores globales, y la dimensión de afinidad se omite repartiendo su peso si no defines keywords.",
        "El descarte se guarda en servidor y el ranking se recalcula sin él, de modo que no vuelve a aparecer lo ya rechazado.",
      ],
      bullets: [
        "Bandas Caliente, Atractiva, Tibia y Descarte para cortar el listado por umbral.",
        "La dimensión de competencia se normaliza contra la media de ofertas recibidas por segmento CPV en 24 meses.",
        "El clasificador SAP es auditable: la API devuelve los términos que más pesaron en su probabilidad para un expediente dado.",
      ],
    },
    {
      kicker: "Precio y competencia",
      icono: "precio",
      h2: "Cuánto hay que bajar, y contra quién",
      parrafos: [
        "La pregunta operativa no es cuánto vale el contrato, sino cuánto hay que bajar para ganarlo en ese segmento. Se calcula la baja media por empresa, órgano, CPV y comunidad autónoma; con comparables suficientes, la licitación trae escenarios por cuantiles —robustos, indicativos o insuficientes según la muestra— y un intervalo p10/p50/p90 con la versión del modelo que lo generó.",
        "El módulo competitivo trabaja sobre las adjudicaciones del propio CODICE: cuota en el universo tecnológico observado, concentración HHI y dossier por competidor sobre un maestro canónico con NIF normalizado, alias y UTEs. Del lado comprador, la ficha de cada órgano muestra qué publica y con qué resultado.",
      ],
      bullets: [
        "Los escenarios son descriptivos: no devuelven probabilidad de ganar, y así está escrito en el código.",
        "La calibración mide la cobertura empírica real del intervalo contra bajas ya resueltas y responde «insuficiente» con menos de 30 pares.",
        "Renovaciones: contratos que vencen con fecha de fin efectiva, riesgo de cambio de proveedor y orden por vencimiento o por oportunidad.",
        "El órgano es el texto que publica la fuente: hay agregación y búsqueda sin acentos, pero no un maestro normalizado de administraciones.",
      ],
    },
    {
      kicker: "Pliegos y flujo",
      icono: "pliegos",
      h2: "Qué pide el pliego, y qué haces después con lo que decides",
      parrafos: [
        "Un proceso nocturno extrae el texto de hasta 300 documentos por pasada y calcula embeddings sobre 100. Con eso, una licitación se resume al vuelo —objeto, importes, plazos, requisitos y riesgos— y el asistente responde citando los fragmentos que ha usado. El pliego alimenta además la señal de tecnología, que la ficha desglosa entre título, clasificador y documentos.",
        "Las reglas de vigilancia se definen por keyword, CPV, importe y comunidad, con previsualización de cuántas coincidencias tienen antes de guardarlas. Lo que decides trabajar pasa al tablero de oportunidades: estado, responsable, motivo de go/no-go, precio ofertado e importe adjudicado, con métricas de embudo.",
      ],
      bullets: [
        "El procesado va por lotes y con cola pendiente: no todo el catálogo tiene los pliegos analizados, y la interfaz lo indica en lugar de improvisar.",
        "El asistente tiene presupuesto de gasto y corte automático si el proveedor de modelo falla.",
        "API REST documentada en OpenAPI, con autenticación por clave con ámbitos y rotación con periodo de gracia; las claves las provisiona el operador.",
      ],
    },
  ],

  faqKicker: "FAQ",
  faqTitulo: "Preguntas frecuentes",
  // Tres preguntas, no seis. Las otras tres reformulaban con otras palabras lo
  // que las secciones acababan de explicar —qué entra en la base, de dónde
  // salen los datos y si se analizan todos los pliegos—; sus dos afirmaciones
  // que no estaban en el cuerpo (Ley 37/2007 y "no sustituye a la fuente
  // oficial") viven ahora como bullets de "Corpus y fuentes". Quedan las que
  // responden algo que el cuerpo no responde.
  faq: [
    {
      pregunta: "¿Me dice la probabilidad de ganar un concurso?",
      respuesta:
        "No, y es una decisión de diseño. Lo que hay es descripción del comportamiento histórico: cuantiles de adjudicaciones comparables, baja media por empresa, órgano, CPV y comunidad autónoma, e intervalo de baja previsto p10/p50/p90 con su calibración. Cuando no hay suficientes pares de predicción y resultado resueltos, la calibración lo declara insuficiente en lugar de dar una cifra.",
    },
    {
      pregunta: "¿Puedo crearme una cuenta yo mismo?",
      respuesta:
        "Hoy no. El acceso es por invitación: se habilita tu email o el dominio de tu empresa y entras con Google. Por eso el botón principal es solicitar acceso y no crear una cuenta. La sesión usa cookie httpOnly con protección CSRF, y el segundo factor TOTP está soportado en la API, con códigos de recuperación y verificación en el login.",
    },
    {
      pregunta: "¿Qué pasa con mis datos y con lo que guardo dentro?",
      respuesta:
        "Los datos de mercado son globales y compartidos; lo tuyo —perfil de scoring, reglas de vigilancia, favoritos, vistas guardadas y oportunidades— queda asociado a tu usuario y a tu organización. Desde la pantalla de cuenta puedes exportar todos tus datos y eliminar la cuenta con confirmación explícita; el borrado anonimiza tu histórico y revoca de paso tus sesiones y claves de API.",
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

  cierreTitulo: "Compruébalo sobre vuestros propios concursos",
  cierreTexto:
    "Todo lo que hay en esta página se puede señalar en el código: de dónde vienen " +
    "los datos, cada cuánto entran, qué se filtra y qué no se calcula. Si tu equipo " +
    "vende tecnología enterprise a la administración pública española y quiere verlo " +
    "sobre sus propios expedientes, escribe y lo vemos.",
  // Antes repetía entera la FAQ de "¿puedo crearme una cuenta?". Ahora sólo
  // remite a ella.
  cierreNota: "El acceso es por invitación.",
};
