# Taxonomía tecnológica

Qué labels de tecnología reconoce TenderFlow, de qué tipo es cada uno y por
qué existe. La fuente de verdad es `config/keywords.py` (`TECHNOLOGY_KEYWORDS`,
`TECH_CATEGORIAS`, `TECH_LABEL_TIPO`, `TECH_DEFINICIONES`); este documento
explica el criterio, no lo sustituye. Decisión de producto: plan de arquitectura v2 (2026-09), «no
salir de TI» — se ensancha la taxonomía por categorías, no por sectores.

## Dos tipos de label

| Tipo | Qué nombra | Ejemplo de título que casa |
|---|---|---|
| `fabricante` | Productos y módulos de un vendor concreto | «Mantenimiento SAP S/4HANA» |
| `categoria` | Qué se compra, sin decir de quién | «Implantación de un ERP» |

Los dos tipos conviven en el mismo dict porque todo consumidor del diccionario
—`scraper.filters` (ingesta), `services.ml.tech_classifier` (multi-etiqueta),
`services.tech_signal` (pliegos), `services.analytics.tecnologias`
(analítica), `services.llm_tech_labeling` (vocabulario cerrado del LLM)—
itera sus claves sin distinguirlas. `TECH_LABEL_TIPO` es donde se distingue
cuando hace falta (UI, documentación, este fichero).

`TECH_DEFINICIONES` resume en una frase lo que cubre cada label y viaja en la
pregunta del etiquetado por LLM: con el nombre solo, el modelo lee
`DESARROLLO` como desarrollo nuevo y deja sin etiqueta el mantenimiento de una
aplicación a medida, que sus keywords sí cubren. Cada definición resume su
lista de keywords y la fila de las tablas de abajo; si cambia una, cambian las
tres.

## Labels

### Fabricantes

| Label | Etiqueta UI | Motivo |
|---|---|---|
| `SAP` | SAP | La práctica fundacional del producto; única con clasificador binario propio y gating de ingesta por defecto (`ML_TECH_GATING_PRACTICES`). |
| `SALESFORCE` | Salesforce | CRM cloud dominante en administración autonómica y sanidad; práctica habitual del integrador objetivo. |
| `ORACLE` | Oracle | Base de datos y ERP (EBS, Fusion, PeopleSoft) presentes en la mayoría de grandes organismos. |
| `MICROSOFT` | Microsoft Dynamics / Azure | Dynamics, Power Platform, Azure y 365: el vendor más transversal del sector público español. |
| `SERVICENOW` | ServiceNow | ITSM de referencia en administraciones grandes; contratos de licencias y evolutivos recurrentes. |
| `WORKDAY` | Workday | HCM cloud; nicho pequeño pero de importe alto (universidades, entes instrumentales). |
| `IBM` | IBM | Maximo, Cognos, WebSphere, DB2, AS/400: parque instalado enorme y contratos de mantenimiento largos. |
| `OPENTEXT` | OpenText | Gestión documental y ECM (Documentum, Content Server) en organismos con archivo electrónico maduro. |
| `UNIT4` | Unit4 | ERP (Agresso) frecuente en universidades y fundaciones públicas. |
| `META4` | Meta4 | Nóminas y RRHH (PeopleNet) muy extendido en ayuntamientos y CCAA. |
| `SOPRA` | Sopra | Sopra HR (HR Access, Pleiades) y Sopra Banking; también aparece como integrador en pliegos SAP. |
| `SAGE` | Sage | ERP de gama media (X3, 200, Despachos) en entes locales y sociedades públicas. |
| `INFOR` | Infor | ERP industrial (LN, M3, CloudSuite, Baan) en empresas públicas y puertos. |

### Categorías (2026-09-14, ampliado 2026-09-27)

| Label | Etiqueta UI | Motivo |
|---|---|---|
| `ERP` | ERP (genérico) | El pliego pide «un ERP» o «un sistema de gestión económico-financiera» sin nombrar vendor; antes ese expediente no tenía label aunque fuese el negocio central del integrador. |
| `CRM` | CRM (genérico) | Igual que ERP para la relación con el cliente o el ciudadano: plataformas de atención ciudadana, contact center, CRM sin marca. |
| `CLOUD_INFRA` | Infraestructura, cloud y redes | Nube, IaaS/PaaS/SaaS, contenedores, virtualización, CPD, almacenamiento, backup y redes de datos (electrónica de red, cableado estructurado, wifi): la capa que el integrador vende junto a cualquier producto. |
| `CIBERSEGURIDAD` | Ciberseguridad | SOC, SIEM, EDR, ENS, auditorías y pentest: la línea de contratación TI que más crece y que no cabía en ningún fabricante. |
| `DATOS_IA` | Datos e IA | BI, cuadros de mando, data warehouse/lake, IA y aprendizaje automático: demanda nueva que llega sin marca (o con marca que no está en la lista). |
| `DESARROLLO` | Desarrollo de software | Desarrollo a medida, mantenimiento evolutivo, factoría de software, apps y APIs: el grueso del CPV 72 no nombra ningún producto. |
| `GIS` | GIS y geoinformación | Sistemas de información geográfica, IDE, geoportales y visores: vertical propia de administración local y autonómica. |
| `SANIDAD_DIGITAL` | Sanidad digital | Historia clínica electrónica, receta electrónica, HIS/PACS, telemedicina: el mayor comprador TI autonómico habla con este vocabulario. |
| `ADMIN_ELECTRONICA` | Administración electrónica | Sede, registro y firma electrónicos, tramitación, interoperabilidad, gestores de expedientes, archivo electrónico: obligación legal (Ley 39/2015) que genera contratación constante. |
| `RRHH_NOMINA` | RRHH y nómina | Sistema o aplicación de nóminas, gestión de recursos humanos, portal del empleado, sin fabricante nombrado: una nómina no es un ERP, y quien la busca no quiere que se le mezcle con la gestión económico-financiera. |
| `GESTION_DOCUMENTAL` | Gestión documental | Gestor documental, sistema o plataforma de gestión documental, ECM, Alfresco o Nuxeo: la custodia y el flujo de documentos digitales, no la tramitación del expediente que los contiene. |
| `PUESTO_TRABAJO` | Puesto de trabajo y soporte | Ordenadores de sobremesa y portátiles, equipos y material informático, microinformática, CAU, service desk, ofimática: el hardware y el soporte del usuario final. |

### Migración de keywords (D2, 2026-09-27)

Las diez keywords de nóminas y RRHH (`sistema de nóminas`, `software de
nóminas`, `sistema de gestión de recursos humanos`, …) salen de `ERP` y pasan
a `RRHH_NOMINA`; las cinco de gestor documental (`gestor documental`,
`sistema de gestión documental`, …) salen de `ADMIN_ELECTRONICA` y pasan a
`GESTION_DOCUMENTAL`. Una fila cuya única señal fuera una de estas keywords
**cambia de familia** la próxima vez que se reingiera (resiembra +
reclasificación), no retroactivamente: lo ya persistido con `ERP` o
`ADMIN_ELECTRONICA` por esa keyword no se reescribe solo. Ver «Efectos de
cambiar la semilla» más abajo.

## Frontera de TI (D1)

Qué cuenta como TI, antes de decidir a qué familia pertenece (2026-09-27):

- **Dentro**: software (licencias, SaaS, desarrollo, mantenimiento de
  aplicaciones), servicios TI (soporte, CAU, outsourcing, consultoría TI),
  infraestructura (cloud, hosting, CPD, redes de datos, virtualización,
  servidores, almacenamiento, backup), ciberseguridad, datos/BI/IA,
  administración electrónica, sanidad digital, GIS y hardware de puesto.
- **Fuera**: formación sobre herramientas (salvo dentro de una implantación),
  suscripciones a contenidos (revistas, bases de datos bibliográficas o
  clínicas), telefonía de voz, publicidad y eventos, y obra civil o
  climatización del CPD.
- Los contratos menores ya adjudicados siguen siendo TI.

## Lenguas cooficiales

La PSCP (Catalunya) publica en catalán, Euskadi en euskera y Galicia en
gallego. Con un diccionario solo en castellano, «desenvolupament de
programari», «software garapena» o «desenvolvemento de software» no casaban
con nada, y eso explicaba parte del 0,46 % de positivos de PSCP (ver
`docs/IMPROVEMENT_BACKLOG.md`, ítem del corpus PSCP).

Cada categoría lleva, además del castellano, las formas en catalán, euskera y
gallego **cuando difieren**; el gallego coincide a menudo con el castellano y
entonces no se repite. Los fabricantes no lo necesitan: «SAP» se escribe igual
en los cuatro idiomas.

Dos particularidades:

- **Euskera**: el sustantivo se declina («zibersegurtasun zerbitzuak» frente a
  «zibersegurtasuna»). Para los términos que encabezan compuestos se lista la
  forma determinada y la raíz. No se intenta cubrir toda la declinación; es un
  suelo, y la tabla `tecnologias_keywords` admite añadir formas desde `/ops`.
- **Catalán**: la ela geminada va con punto volado (`intel·ligència`). El filtro
  compila con `re.escape`, así que el punto es literal y los límites de palabra
  siguen funcionando.

## Criterio de precisión

- **Sintagmas antes que palabras sueltas.** «datos», «software», «seguridad»
  o «contenedores» a secas casan con todo (incluidos contenedores de basura);
  solo entran dentro de una frase («analítica de datos», «plataforma de
  contenedores»).
- **Acrónimos cortos sí**, porque `services.tecnologias_diccionario.patrones`
  compila con límites de palabra: `erp` no casa dentro de «interpretación» ni
  `gis` dentro de «registro». `services/ml/classifier_pipeline._keyword_fallback_score`
  (tier `rules` del clasificador) aplica el mismo criterio desde el 2026-09-14.
- **Sin duplicados entre labels.** Una keyword pertenece a un único label; el
  test `tests/test_taxonomia_tecnologica.py` fija el conjunto de excepciones
  intencionales (hoy vacío).
- **Los términos que no empiezan (o no acaban) en letra llevan otro límite.**
  El patrón de siempre era `\b(kw1|kw2|…)\b`, y con él **`.net` no podía casar
  nunca**: `\b` antes de un punto exige un carácter de palabra pegado, así que
  sólo casaba dentro de otra palabra (`asp.net`) y jamás en «plataforma .NET»,
  que es como aparece en los pliegos. La keyword estaba en el diccionario desde
  su primera versión sin clasificar nada, y sólo se vio al escribir el test que
  compila cada término contra sí mismo (2026-09-15).

  Desde entonces el patrón lo construye `config.keywords.patron_de_keywords`,
  que pone `\b` donde el término empieza o acaba en carácter de palabra y una
  aserción negativa donde no. Lo usan el diccionario vigente
  (`services.tecnologias_diccionario.patrones`), el filtro del scraper y el
  test, para que arreglar un caso lo arregle en los tres. El punto se excluye a
  la izquierda a propósito: `.net` sigue sin casar dentro de `asp.net`, que es
  un producto distinto con su propia entrada.
- **Fuera lo que no es TI** aunque lo parezca: «teleasistencia» (servicio
  social), «gestión documental» a secas (custodia física), «página web» a secas
  (aparece en descripciones como «consultar en la página web»).

## Efectos de cambiar la semilla

- **`filter_version` cambia solo**: es el hash del contenido del diccionario
  (`services/tecnologias_diccionario._hash_de`). La serie analítica «por
  tecnología» se corta en la fecha de la resiembra, y los conteos de antes y
  después no son comparables (ADR-014; nota en
  `docs/frontend-data-invariants.md`).
- **Añadir aquí no basta para producción**: hay que resembrar
  (`POST /api/v1/tecnologias/keywords/sembrar` o desde `/ops`). La siembra es
  idempotente y no reactiva lo que alguien desactivó a mano.
- **Clasificador multi-etiqueta**: las categorías nacen sin positivos, así que
  `train` las deja en el tier `rules` (keywords con umbral propio) hasta que el
  feedback humano o el etiquetado LLM las alimente. Un modelo serializado antes
  del cambio conserva sus trece labels hasta que se reentrena.
- **Gating de ingesta**: no cambia. `ML_TECH_GATING_PRACTICES` sigue nombrando
  qué labels aceptan un expediente; añadir una categoría al diccionario no la
  convierte en criterio de aceptación.

## Cómo añadir un label

1. Entrada en `TECHNOLOGY_KEYWORDS` (lista en minúsculas, sintagmas, con las
   formas ca/eu/gl si difieren).
2. Entrada en `TECH_CATEGORIAS` (etiqueta UI), en `TECH_LABEL_TIPO` y en
   `TECH_DEFINICIONES` (una frase para el LLM). El módulo falla al importar si
   los cuatro mapas no declaran los mismos labels.
3. Fila en la tabla de arriba con su motivo en una línea.
4. `tests/test_taxonomia_tecnologica.py` verde (≥ 5 keywords, sin duplicados,
   detección sobre títulos reales).
5. Resembrar en cada entorno.
