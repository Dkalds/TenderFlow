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

/** Los tres verbos del producto, arriba del todo. Cada uno resume una
 * consola real (Radar / baja de referencia / módulo competitivo); el detalle
 * verificable de cada afirmación vive en la sección correspondiente. */
export interface PilarLanding {
  titulo: string;
  texto: string;
}

export interface SeccionLanding {
  /** Etiqueta corta de navegación visual ("Corpus", "Fuentes", …). */
  kicker: string;
  h2: string;
  parrafos: string[];
  bullets?: string[];
  /** Enlace interno hacia la superficie pública de datos, cuando la sección
   * habla de algo que se puede ver sin cuenta. Además de útil para el lector,
   * reparte autoridad interna hacia los hubs indexables. */
  enlace?: { texto: string; href: string };
}

export interface PreguntaFrecuente {
  pregunta: string;
  respuesta: string;
}

export interface ContenidoLanding {
  /** 50-60 caracteres. */
  metaTitle: string;
  /** 150-160 caracteres. */
  metaDescription: string;
  /** Categoría de producto, visible antes que el h1: qué clase de cosa es esto. */
  eyebrow: string;
  h1: string;
  subtitulo: string;
  ctaPrimario: string;
  ctaSecundario: string;
  /** Línea de confianza bajo los CTAs: fuentes y modelo de acceso, verificables. */
  notaFuentes: string;
  pilares: PilarLanding[];
  familiasTitulo: string;
  /** Diccionario de familias de producto (scraper/filters.py): el corpus se
   * acota por señal de estas trece marcas, y por eso se pueden enumerar. */
  familias: string[];
  secciones: SeccionLanding[];
  faq: PreguntaFrecuente[];
  /** Bloque de cierre, tras las preguntas frecuentes. */
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

  // El espacio duro en "a qué" evita que el corte de línea deje una "a"
  // huérfana a final de renglón en los anchos de hero más habituales.
  h1: "Licitaciones de tecnología del sector público: decide dónde pujar, a\u00A0qué precio y contra quién",
  subtitulo:
    "TenderFlow es un radar de licitaciones públicas de tecnología enterprise en " +
    "España. Acota el mercado a los expedientes con señal TI real y les añade el " +
    "contexto de decisión: scoring de oportunidad con tu perfil, baja de " +
    "referencia por segmento, competencia por órgano y lectura de pliegos con citas.",

  // El alta self-service está desactivada en producción: `ALLOW_SELF_REGISTRATION`
  // es `False` por defecto y no se declara en `render.yaml`, así que
  // `POST /auth/register` responde 403; y el login con Google es fail-closed sin
  // allowlist. Un "crea tu cuenta gratis" sería una promesa que acaba en error.
  ctaPrimario: "Solicita acceso",
  ctaSecundario: "Cómo funciona",

  notaFuentes:
    "Fuentes oficiales: PLACSP cada cuatro horas, TED y los RSS de Galicia y " + "Euskadi. Acceso por invitación.",

  pilares: [
    {
      titulo: "Dónde pujar",
      texto:
        "Radar ordena la bandeja diaria por score de oportunidad sobre seis " +
        "dimensiones, con pesos configurables por usuario. Bandas Caliente, " +
        "Atractiva, Tibia y Descarte para cortar por umbral, y lo descartado " +
        "no vuelve a aparecer.",
    },
    {
      titulo: "A qué precio",
      texto:
        "Baja media por empresa, órgano, CPV y comunidad autónoma; escenarios " +
        "por cuantiles sobre adjudicaciones comparables y un intervalo de baja " +
        "previsto p10/p50/p90 con su calibración declarada.",
    },
    {
      titulo: "Contra quién",
      texto:
        "Cuota y concentración HHI sobre las adjudicaciones oficiales, dossier " +
        "por competidor con NIF normalizado, alias y UTEs, e historial de lo " +
        "que publica cada órgano de contratación y con qué resultado.",
    },
  ],

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

  secciones: [
    {
      kicker: "Corpus",
      h2: "Un radar tecnológico, no un censo de toda la contratación pública",
      parrafos: [
        "TenderFlow no indexa toda la contratación pública española. Solo entra en el corpus el expediente con señal de tecnología enterprise: coincidencia con el diccionario de trece familias de producto —SAP, Salesforce, Oracle, Microsoft, ServiceNow, Workday, IBM, OpenText, Unit4, Meta4, Sopra, Sage e Infor—, rescate del clasificador sobre CPV 48 (software) y 72 (servicios TI), o consulta directa por esos CPV en el caso de TED. Todo lo que se guarda queda marcado con el motivo por el que entró.",
        "La decisión es deliberada. Comparar precios, competencia y comportamiento de órganos exige un mercado acotado y homogéneo; en un índice general esas comparaciones no significan nada. Si tu negocio es obra pública, sanidad o suministros generales, esta herramienta no te sirve.",
      ],
      bullets: [
        "Match por palabra completa sobre título y descripción del anuncio, no por coincidencia parcial.",
        "El rescate del clasificador se limita a CPV 48 y 72, y hoy solo la práctica SAP admite expedientes sin keyword.",
        "Cada licitación conserva la versión del filtro y del clasificador con la que entró, así que siempre se sabe con qué criterio se admitió cada expediente.",
      ],
      enlace: { texto: "Explora las licitaciones por código CPV", href: "/cpv" },
    },
    {
      kicker: "Fuentes",
      h2: "Fuentes oficiales, cadencia declarada y límites por escrito",
      parrafos: [
        "La fuente principal es el feed ATOM de la Plataforma de Contratación del Sector Público, que se recorre cada cuatro horas con cursor incremental, escritura idempotente e historial de cambios por expediente. Se suman TED, para anuncios con ejecución en España dentro de CPV 48 y 72, y los RSS oficiales de Contratos de Galicia y Open Data Euskadi.",
        "Las dos últimas son fuentes de descubrimiento reciente: no aportan histórico completo ni todos los cambios posteriores del expediente, y el producto no las presenta como si lo hicieran. No hay cobertura autonómica homogénea.",
      ],
      bullets: [
        "Parser CODICE/UBL sobre el XML oficial, con reintentos y cortocircuito ante fallos de la fuente.",
        "Los campos que la fuente no publica quedan vacíos, y se mide el porcentaje de nulos en órgano de contratación, importe y CPV.",
        "Carril por NIF: si vigilas una empresa se conservan sus adjudicaciones aunque el expediente no dé señal tecnológica, desde que la das de alta.",
      ],
      enlace: {
        texto: "Ver los anuncios publicados, por comunidad autónoma",
        href: "/licitaciones",
      },
    },
    {
      kicker: "Scoring",
      h2: "Decide a qué presentarte: scoring de oportunidad con tu propio perfil",
      parrafos: [
        "El ranking ordena el mercado abierto por potencial comercial sobre seis dimensiones: importe, plazo, competencia esperada, margen, afinidad y señal técnica. Los pesos son configurables y cada usuario guarda su perfil —pesos, keywords de afinidad, CPV y rango de importe—; sin perfil se aplican los valores globales. Si no defines keywords de afinidad, esa dimensión se omite y su peso se reparte entre las demás.",
        "Radar es la consola de triaje diario: la bandeja llega ordenada por score y cada señal se sigue, se descarta o se abre. El descarte se guarda en servidor y el ranking se recalcula sin él, de modo que no vuelve a aparecer lo ya rechazado.",
      ],
      bullets: [
        "Bandas Caliente, Atractiva, Tibia y Descarte para cortar el listado por umbral.",
        "La dimensión de competencia se normaliza contra la media de ofertas recibidas por segmento CPV en 24 meses.",
        "El clasificador SAP es auditable: la API devuelve los términos que más pesaron en su probabilidad para un expediente dado.",
      ],
    },
    {
      kicker: "Precio",
      h2: "Decide a qué precio: baja de referencia y escenarios sobre comparables",
      parrafos: [
        "La pregunta operativa no es cuánto vale el contrato, sino cuánto hay que bajar para ganar en ese segmento. TenderFlow calcula la baja media agregada por empresa, órgano, CPV y comunidad autónoma, usando el presupuesto del lote cuando la adjudicación tiene uno resuelto y descartando los pares en los que el importe adjudicado supera el presupuesto en más de un 50 %.",
        "Cuando hay adjudicaciones comparables suficientes, la licitación trae escenarios de precio por cuantiles históricos —etiquetados como robustos, indicativos o insuficientes según la muestra— y un intervalo de baja previsto (p10/p50/p90) con la versión del modelo que lo generó.",
      ],
      bullets: [
        "Los escenarios son descriptivos: no devuelven probabilidad de ganar, y así está escrito en el código.",
        "La calibración mide la cobertura empírica real del intervalo contra bajas ya resueltas y responde «insuficiente» con menos de 30 pares.",
        "Cuando el expediente ya está adjudicado, la predicción se contrasta con la baja real.",
      ],
    },
    {
      kicker: "Competencia",
      h2: "Contra quién compites y qué historial tiene ese órgano",
      parrafos: [
        "El módulo competitivo trabaja sobre las adjudicaciones extraídas del propio CODICE: cuota dentro del universo tecnológico observado, concentración HHI por CPV, comunidad autónoma, órgano y tecnología, dossier por competidor y listado paginado de sus adjudicaciones. Detrás hay un maestro canónico de adjudicatarios con NIF normalizado, alias, UTEs y cola de revisión humana para los emparejamientos dudosos.",
        "Del lado comprador, el ranking de órganos y su ficha muestran qué publica cada uno y con qué resultado, y la línea de tiempo del contrato ordena publicación, adjudicación, formalización, modificaciones de importe, prórrogas y anulaciones.",
      ],
      bullets: [
        "Renovaciones: contratos que vencen con fecha de fin efectiva, riesgo de cambio de proveedor y orden por vencimiento o por oportunidad.",
        "Resumen de cartera en juego por empresa e importe total en riesgo alto.",
        "El órgano es el texto que publica la fuente: hay agregación y búsqueda sin acentos, pero no un maestro normalizado de administraciones.",
      ],
    },
    {
      kicker: "Pliegos",
      h2: "Qué pide el pliego, sin leerte doscientas páginas",
      parrafos: [
        "Un proceso nocturno descarga y extrae el texto de hasta 300 documentos por pasada, y trocea y calcula embeddings sobre hasta 100 de ellos. Sobre ese texto, una licitación puede resumirse al vuelo —objeto, órgano, importes y plazos, requisitos clave y riesgos— y el asistente conversacional responde preguntas sobre el corpus.",
        "Sobre una licitación concreta, el asistente cita los fragmentos de pliego que ha utilizado; en modo corpus general la recuperación es léxica sobre los anuncios. El texto del pliego alimenta además la señal de tecnología: la ficha muestra por separado lo que dice el título, lo que dice el clasificador y lo que aparece en los documentos, con su evidencia.",
      ],
      bullets: [
        "El resumen avisa en su primer evento de si hay texto de pliego disponible; si no lo hay, lo dice.",
        "El asistente tiene presupuesto de gasto y corte automático si el proveedor de modelo falla.",
        "El procesado va por lotes y con cola pendiente: no todo el catálogo tiene los pliegos analizados.",
      ],
    },
    {
      kicker: "Flujo",
      h2: "Después de decidir: vigilancia, alertas y pipeline comercial",
      parrafos: [
        "Las reglas de vigilancia se definen por keyword, CPV, importe mínimo y comunidad autónoma, con frecuencia inmediata, diaria o semanal, previsualización del número real de coincidencias antes de guardarlas y aviso por email más notificación en la aplicación. También puedes vigilar empresas concretas y recibir sus movimientos después de cada ingesta.",
        "Lo que decides trabajar pasa al tablero de oportunidades: estados de identificada a presentada, ganada o perdida, responsable, motivo de la decisión de go/no-go, precio ofertado e importe adjudicado, con métricas de embudo y agenda de compromisos por vencimiento.",
      ],
      bullets: [
        "Favoritos, vistas guardadas y campana de notificaciones alimentada por un canal de eventos en vivo.",
        "API REST documentada en OpenAPI, con autenticación por clave con ámbitos y rotación con periodo de gracia; las claves las provisiona el operador.",
        "Exportación a CSV de los resultados con los filtros activos.",
      ],
    },
  ],

  faq: [
    {
      pregunta: "¿Qué licitaciones entran en la base y cuáles se quedan fuera?",
      respuesta:
        "Entran los expedientes con señal de tecnología enterprise: los que coinciden con el diccionario de trece familias de producto (SAP, Salesforce, Oracle, Microsoft, ServiceNow, Workday, IBM, OpenText, Unit4, Meta4, Sopra, Sage e Infor), los que rescata el clasificador dentro de CPV 48 y 72, y los que TED devuelve para esos mismos CPV. Obra pública, sanidad, suministros generales o servicios no TI no están. Es un radar sectorial, no un buscador de toda la contratación pública española.",
    },
    {
      pregunta: "¿De dónde salen los datos y cada cuánto se actualizan?",
      respuesta:
        "De fuentes oficiales reutilizadas al amparo de la Ley 37/2007. La principal es el feed ATOM de la Plataforma de Contratación del Sector Público, que se recorre cada cuatro horas con cursor incremental, escritura idempotente e historial de cambios por expediente. Se suman TED (anuncios con ejecución en España y CPV 48/72) y los RSS oficiales de Galicia y Open Data Euskadi, que son de descubrimiento reciente: no aportan histórico completo ni todos los cambios posteriores. No es tiempo real, y TenderFlow no sustituye a la consulta de la fuente oficial antes de presentar una oferta.",
    },
    {
      pregunta: "¿Me dice la probabilidad de ganar un concurso?",
      respuesta:
        "No, y es una decisión de diseño. Lo que hay es descripción del comportamiento histórico: cuantiles de adjudicaciones comparables, baja media por empresa, órgano, CPV y comunidad autónoma, e intervalo de baja previsto p10/p50/p90 con su calibración. Cuando no hay suficientes pares de predicción y resultado resueltos, la calibración lo declara insuficiente en lugar de dar una cifra.",
    },
    {
      pregunta: "¿Analiza los pliegos de todas las licitaciones?",
      respuesta:
        "No de todas. Los documentos se descargan y se extraen en un proceso nocturno de hasta 300 por pasada, y de ahí se trocean y embeben hasta 100, con una cola de pendientes que se drena por lotes cada noche. Cuando una licitación tiene texto extraído, dispones de resumen ejecutivo, preguntas con cita del documento y señal de tecnología a partir del pliego. Cuando no lo tiene, la interfaz lo indica en lugar de improvisar.",
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

  cierreTitulo: "Compruébalo sobre vuestros propios concursos",
  cierreTexto:
    "Todo lo que hay en esta página se puede señalar en el código: de dónde vienen " +
    "los datos, cada cuánto entran, qué se filtra y qué no se calcula. Si tu equipo " +
    "vende tecnología enterprise a la administración pública española y quiere verlo " +
    "sobre vuestros propios concursos, pide acceso y lo abrimos.",
  cierreNota: "El acceso es por invitación: se habilita tu email o el dominio de tu empresa " + "y entras con Google.",
};
