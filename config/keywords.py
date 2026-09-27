"""Keywords por tecnología para filtrar licitaciones del sector público.

Consumidores: ``scraper.filters``, ``scheduler.concept_drift``.

Dos tipos de etiqueta (2026-09-14, plan de arquitectura v2, «no salir de TI»)
-----------------------------------------------------------------------------
* **Fabricante** (``SAP``, ``SALESFORCE``, …): la taxonomía histórica. Cada
  lista nombra productos y módulos de un vendor concreto.
* **Categoría** (``ERP``, ``CRM``, ``CLOUD_INFRA``, ``CIBERSEGURIDAD``,
  ``DATOS_IA``, ``DESARROLLO``, ``GIS``, ``SANIDAD_DIGITAL``,
  ``ADMIN_ELECTRONICA``, ``RRHH_NOMINA``, ``GESTION_DOCUMENTAL``,
  ``PUESTO_TRABAJO``): qué se compra, sin decir de quién. Ensanchan la
  taxonomía **dentro** de TI: un integrador vende «un ERP» o «un SOC» tanto
  como vende SAP.

Las dos conviven en el mismo dict porque todo lo que consume el diccionario
—filtro, clasificador multi-etiqueta, señal de pliegos, analítica— itera sus
claves sin distinguirlas; :data:`TECH_LABEL_TIPO` es donde se distingue cuando
hace falta (UI, documentación).

Idiomas cooficiales
-------------------
La PSCP (Catalunya) publica en catalán, Euskadi en euskera y Galicia en
gallego. Un vocabulario solo en castellano explicaba parte del 0,46 % de
positivos de PSCP: «desenvolupament de programari» no casa con «desarrollo de
software». Por eso cada categoría lleva, además del castellano, las formas en
catalán, euskera y gallego **cuando difieren** (el gallego coincide a menudo
con el castellano, y entonces no se repite). Los fabricantes no lo necesitan:
«SAP» se escribe igual en los cuatro idiomas.

Criterio de precisión
---------------------
Se prefieren términos de varias palabras a palabras sueltas: «datos»,
«software» o «seguridad» a secas casan con todo, así que solo entran dentro
de sintagmas («analítica de datos», «desarrollo de software», «auditoría de
seguridad»). Los acrónimos cortos (``erp``, ``gis``, ``siem``) sí entran
porque el filtro compila con límites de palabra (véase
``services.tecnologias_diccionario.patrones``): «gis» no casa dentro de
«registro».
"""

from __future__ import annotations

import functools
import re
import unicodedata
from collections.abc import Iterable
from typing import Literal

# Palabras clave para filtrar licitaciones SAP
SAP_KEYWORDS: list[str] = [
    # Plataforma principal
    "sap",
    "s/4hana",
    "s4hana",
    "s/4 hana",
    "hana",
    "abap",
    "fiori",
    # Módulos funcionales
    "sap erp",
    "sap ecc",
    "sap basis",
    "sap mm",
    "sap fi",
    "sap fi/co",
    "sap co",
    "sap sd",
    "sap hcm",
    "sap hr",
    "sap pi",
    "sap po",
    "sap pm",
    "sap ps",
    "sap qm",
    "sap wm",
    "sap ewm",
    "sap tm",
    "sap srm",
    "sap crm",
    "sap ssm",
    "sap bi",
    "sap bo",
    "sap bw",
    "sap bpc",
    "sap grc",
    "sap mdg",
    "sap mdm",
    "sap isu",
    "sap is-u",
    "sap re-fx",
    "sap refx",
    "sap re/fx",
    "sap apo",
    "sap scm",
    "sap ibp",
    "sap slm",
    "sap clm",
    "sap ariba",
    "sap fieldglass",
    "sap concur",
    "sap analytics cloud",
    "sac sap",
    # Suite cloud
    "successfactors",
    "ariba",
    "concur",
    "fieldglass",
    "sap cx",
    "sap customer experience",
    # Infraestructura / tecnología
    "netweaver",
    "bw/4hana",
    "bw4hana",
    "sap solution manager",
    "solman",
    "businessobjects",
    "business objects",
    "crystal reports",
    "sap oss",
    "sap early watch",
    "sap lumira",
    "sap build",
    "sap integration suite",
    "sap btp",
    "business technology platform",
    "sap cloud platform",
    # Términos genéricos asociados
    "implantación sap",
    "migración sap",
    "mantenimiento sap",
    "soporte sap",
    "consultoría sap",
    "formación sap",
    "licencias sap",
    "upgrade sap",
    "actualización sap",
]

# Keywords por tecnología (multi-vendor).
# El scraper filtra licitaciones que coincidan con al menos una tecnología.
# ── SEMILLA, no fuente de verdad (C5.6, D28, v126) ──────────────────────────
#
# Desde v126 el diccionario vigente vive en la tabla `tecnologias_keywords` y se
# edita desde `/ops` sin desplegar. Esto es la **semilla**: lo que se vuelca en
# la tabla cuando está vacía (`services.tecnologias_diccionario.
# sembrar_desde_semilla`) y el respaldo si la base de datos no responde — sin
# él, un fallo de lectura dejaría el filtro sin diccionario, y un filtro sin
# diccionario no descarta nada: mete el censo entero.
#
# Añadir aquí una keyword ya **no** basta para que entre en producción: hay que
# resembrar. Lo que sí sigue estando aquí es la revisión en código de qué
# términos son legítimos, que es lo que una tabla editable no da.
TECHNOLOGY_KEYWORDS: dict[str, list[str]] = {
    "SAP": SAP_KEYWORDS,
    "SALESFORCE": [
        "salesforce",
        "sales cloud",
        "service cloud",
        "marketing cloud",
        "commerce cloud",
        "experience cloud",
        "community cloud",
        "salesforce cpq",
        "salesforce crm",
        "pardot",
        "mulesoft",
        "tableau crm",
        "einstein analytics",
        "salesforce einstein",
        "heroku",
        "apex salesforce",
        "visualforce",
        "lightning",
        "salesforce platform",
        "force.com",
        "data cloud salesforce",
        "implantación salesforce",
        "migración salesforce",
        "mantenimiento salesforce",
        "soporte salesforce",
        "consultoría salesforce",
        "licencias salesforce",
    ],
    "ORACLE": [
        "oracle",
        "oracle erp",
        "oracle cloud",
        "oracle fusion",
        "oracle ebs",
        "e-business suite",
        "oracle hcm",
        "oracle financials",
        "peoplesoft",
        "jd edwards",
        "oracle database",
        "oracle db",
        "oracle weblogic",
        "oracle forms",
        "oracle apex",
        "oracle bi",
        "oracle analytics",
        "oracle integration cloud",
        "oracle soa",
        "primavera oracle",
        "siebel",
        "oracle netsuite",
        "netsuite",
        "pl/sql",
        "plsql",
        "implantación oracle",
        "migración oracle",
        "mantenimiento oracle",
        "soporte oracle",
        "consultoría oracle",
        "licencias oracle",
    ],
    "MICROSOFT": [
        "microsoft dynamics",
        "dynamics 365",
        "dynamics crm",
        "dynamics nav",
        "dynamics ax",
        "dynamics bc",
        "business central",
        "navision",
        "axapta",
        "power platform",
        "power bi",
        "power apps",
        "power automate",
        "microsoft azure",
        "azure devops",
        "sharepoint",
        "microsoft 365",
        "office 365",
        "microsoft teams",
        "sql server",
        "azure sql",
        ".net",
        "dotnet",
        "implantación dynamics",
        "migración dynamics",
        "mantenimiento dynamics",
        "soporte dynamics",
        "consultoría dynamics",
        "licencias dynamics",
        "licencias microsoft",
    ],
    "SERVICENOW": [
        "servicenow",
        "service now",
        "servicenow itsm",
        "servicenow itom",
        "servicenow hrsd",
        "servicenow csm",
        "implantación servicenow",
        "soporte servicenow",
        "licencias servicenow",
    ],
    "WORKDAY": [
        "workday",
        "workday hcm",
        "workday financials",
        "workday adaptive",
        "workday prism",
        "implantación workday",
        "soporte workday",
        "licencias workday",
    ],
    "IBM": [
        "ibm maximo",
        "ibm cognos",
        "ibm websphere",
        "ibm db2",
        "ibm cloud",
        "ibm watson",
        "ibm filenet",
        "ibm bpm",
        "lotus notes",
        "ibm as/400",
        "ibm iseries",
        "rpg ibm",
    ],
    "OPENTEXT": [
        "opentext",
        "open text",
        "documentum",
        "content server",
        "opentext ecm",
        "opentext extended ecm",
    ],
    "UNIT4": [
        "unit4",
        "unit 4",
        "unit4 erp",
        "unit4 financials",
        "agresso",
    ],
    "META4": [
        "meta4",
        "meta 4",
        "meta4 peoplenet",
        "peoplenet",
        "cezanne hr",
    ],
    "SOPRA": [
        "sopra",
        "sopra steria",
        "sap sopra",
        "sopra hr",
        "sopra hr software",
        "hr access",
        "sopra banking",
    ],
    "SAGE": [
        "sage erp",
        "sage x3",
        "sage 200",
        "sage despachos",
        "sage murano",
        "sage 50",
    ],
    "INFOR": [
        "infor erp",
        "infor ln",
        "infor m3",
        "infor cloudsuite",
        "infor os",
        "baan",
    ],
    # ── Categorías (2026-09-14) ─────────────────────────────────────────────
    # Van detrás de los fabricantes a propósito: ``TECH_LABELS`` conserva el
    # orden de inserción y los índices de los trece primeros no se mueven.
    "ERP": [
        # es
        "erp",
        "sistema erp",
        "solución erp",
        "planificación de recursos empresariales",
        "sistema de gestión integrado",
        "sistema integrado de gestión",
        "gestión económico-financiera",
        "sistema de gestión económico-financiera",
        "sistema de información económico-financiero",
        "sistema de gestión económica",
        "contabilidad presupuestaria",
        "sistema de gestión contable",
        "sistema contable",
        "sistema de gestión tributaria",
        # ca
        "planificació de recursos empresarials",
        "sistema de gestió integrat",
        "sistema integrat de gestió",
        "gestió econòmica i financera",
        "gestió economicofinancera",
        "sistema de gestió econòmica",
        "comptabilitat pressupostària",
        "sistema de gestió comptable",
        "sistema comptable",
        "sistema de gestió tributària",
        # eu
        "enpresa baliabideen plangintza",
        "kudeaketa sistema integratua",
        "kudeaketa ekonomiko-finantzarioa",
        "kudeaketa ekonomikoko sistema",
        "aurrekontu kontabilitatea",
        "kontabilitate sistema",
        "zerga kudeaketako sistema",
        "giza baliabideen kudeaketa sistema",
        # gl
        "planificación de recursos empresariais",
        "sistema de xestión integrado",
        "sistema integrado de xestión",
        "xestión económico-financeira",
        "xestión económica e financeira",
        "sistema de xestión económica",
        "contabilidade orzamentaria",
        "sistema de xestión contable",
        "sistema de xestión tributaria",
    ],
    "CRM": [
        # es
        "crm",
        "sistema crm",
        "solución crm",
        "plataforma crm",
        "customer relationship management",
        "citizen relationship management",
        "gestión de relaciones con clientes",
        "gestión de la relación con el cliente",
        "gestión de relaciones con la ciudadanía",
        "plataforma de atención ciudadana",
        "sistema de atención ciudadana",
        "gestión de clientes",
        "plataforma de contact center",
        "solución de contact center",
        "software de contact center",
        "plataforma de centro de contacto",
        "automatización de marketing",
        "gestión de la experiencia de cliente",
        # ca
        "gestió de relacions amb clients",
        "gestió de la relació amb el client",
        "gestió de relacions amb la ciutadania",
        "plataforma d'atenció ciutadana",
        "sistema d'atenció ciutadana",
        "gestió de clients",
        "plataforma de centre de contacte",
        "automatització de màrqueting",
        "gestió de l'experiència de client",
        # eu
        "bezeroekiko harremanen kudeaketa",
        "herritarrekiko harremanen kudeaketa",
        "herritarren arretarako plataforma",
        "herritarren arretarako sistema",
        "bezeroen kudeaketa",
        "kontaktu zentroko plataforma",
        "marketin automatizazioa",
        "bezeroaren esperientziaren kudeaketa",
        # gl
        "xestión de relacións con clientes",
        "xestión da relación co cliente",
        "xestión de relacións coa cidadanía",
        "plataforma de atención cidadá",
        "sistema de atención cidadá",
        "xestión de clientes",
        "automatización de márketing",
        "xestión da experiencia de cliente",
    ],
    "CLOUD_INFRA": [
        # es
        "servicios en la nube",
        "servicios cloud",
        "nube pública",
        "nube privada",
        "nube híbrida",
        "computación en la nube",
        "cloud computing",
        "migración a la nube",
        "infraestructura como servicio",
        "iaas",
        "plataforma como servicio",
        "paas",
        "software como servicio",
        "saas",
        "kubernetes",
        "docker",
        "openshift",
        "orquestación de contenedores",
        "plataforma de contenedores",
        "virtualización",
        "vmware",
        "hiperconvergencia",
        "infraestructura hiperconvergente",
        "centro de datos",
        "centro de proceso de datos",
        "cpd",
        "datacenter",
        "data center",
        "hosting",
        "alojamiento web",
        "cabina de almacenamiento",
        "sistema de almacenamiento",
        "almacenamiento en la nube",
        "copias de seguridad",
        "copia de seguridad",
        "backup",
        "recuperación ante desastres",
        "disaster recovery",
        "suministro de servidores",
        "servidores virtuales",
        # ca
        "serveis al núvol",
        "serveis en el núvol",
        "serveis de núvol",
        "núvol públic",
        "núvol privat",
        "núvol híbrid",
        "computació al núvol",
        "migració al núvol",
        "infraestructura com a servei",
        "plataforma com a servei",
        "programari com a servei",
        "orquestració de contenidors",
        "plataforma de contenidors",
        "virtualització",
        "centre de dades",
        "centre de procés de dades",
        "allotjament web",
        "cabina d'emmagatzematge",
        "sistema d'emmagatzematge",
        "emmagatzematge al núvol",
        "còpies de seguretat",
        "còpia de seguretat",
        "recuperació davant desastres",
        "subministrament de servidors",
        "servidors virtuals",
        # eu
        "hodeiko zerbitzuak",
        "hodeiko zerbitzu",
        "hodei publikoa",
        "hodei pribatua",
        "hodei hibridoa",
        "hodeiko konputazioa",
        "hodeirako migrazioa",
        "azpiegitura zerbitzu gisa",
        "plataforma zerbitzu gisa",
        "softwarea zerbitzu gisa",
        "edukiontzien orkestrazioa",
        "edukiontzi plataforma",
        "birtualizazioa",
        "datu zentroa",
        "datuak prozesatzeko zentroa",
        "web ostatatzea",
        "biltegiratze kabina",
        "biltegiratze sistema",
        "hodeiko biltegiratzea",
        "segurtasun kopiak",
        "segurtasun kopia",
        "hondamendien aurreko berreskuratzea",
        "zerbitzarien hornidura",
        "zerbitzari birtualak",
        # gl
        "servizos na nube",
        "computación na nube",
        "migración á nube",
        "infraestrutura como servizo",
        "plataforma como servizo",
        "software como servizo",
        "orquestración de contedores",
        "plataforma de contedores",
        "aloxamento web",
        "cabina de almacenamento",
        "sistema de almacenamento",
        "almacenamento na nube",
        "copias de seguranza",
        "copia de seguranza",
        "subministración de servidores",
        "servidores virtuais",
        # Redes de datos (D2, 2026-09-27): CLOUD_INFRA es «infraestructura, cloud y
        # redes». Solo sintagmas: «red» a secas casa con saneamiento y agua.
        "electrónica de red",
        "electrònica de xarxa",
        "cableado estructurado",
        "cablejat estructurat",
        "cableado estruturado",
        "red de área local",
        "xarxa d'àrea local",
        "sd-wan",
        "red corporativa",
        "xarxa corporativa",
        "rede corporativa",
        "red wifi",
        "xarxa wifi",
        "rede wifi",
    ],
    "CIBERSEGURIDAD": [
        # es
        "ciberseguridad",
        "seguridad informática",
        "seguridad de la información",
        "seguridad de los sistemas de información",
        "esquema nacional de seguridad",
        "adecuación al ens",
        "certificación ens",
        "cumplimiento del ens",
        "auditoría de seguridad",
        "auditoría de ciberseguridad",
        "análisis de vulnerabilidades",
        "gestión de vulnerabilidades",
        "test de intrusión",
        "pruebas de intrusión",
        "pentest",
        "pentesting",
        "hacking ético",
        "centro de operaciones de seguridad",
        "servicio de soc",
        "servicios de soc",
        "soc 24x7",
        "siem",
        "edr",
        "xdr",
        "mdr",
        "dlp",
        "waf",
        "firewall",
        "cortafuegos",
        "antivirus",
        "gestión de identidades",
        "gestión de identidades y accesos",
        "iam",
        "doble factor de autenticación",
        "autenticación multifactor",
        "cifrado de datos",
        "seguridad perimetral",
        "respuesta a incidentes",
        "ciberincidentes",
        "concienciación en ciberseguridad",
        "zero trust",
        "seguridad gestionada",
        "servicios de seguridad gestionada",
        # ca
        "ciberseguretat",
        "seguretat informàtica",
        "seguretat de la informació",
        "seguretat dels sistemes d'informació",
        "esquema nacional de seguretat",
        "adequació a l'ens",
        "auditoria de seguretat",
        "auditoria de ciberseguretat",
        "anàlisi de vulnerabilitats",
        "gestió de vulnerabilitats",
        "test d'intrusió",
        "proves d'intrusió",
        "centre d'operacions de seguretat",
        "servei de soc",
        "serveis de soc",
        "tallafocs",
        "gestió d'identitats",
        "gestió d'identitats i accessos",
        "autenticació multifactor",
        "xifratge de dades",
        "seguretat perimetral",
        "resposta a incidents",
        "conscienciació en ciberseguretat",
        "seguretat gestionada",
        # eu — el euskera declina el sustantivo («zibersegurtasun zerbitzuak»,
        # «zibersegurtasuna»): se listan la forma determinada y la raíz cuando
        # la raíz es la que aparece en los compuestos de los títulos.
        "zibersegurtasuna",
        "zibersegurtasun",
        "segurtasun informatikoa",
        "informazioaren segurtasuna",
        "informazio sistemen segurtasuna",
        "segurtasun eskema nazionala",
        "segurtasun auditoretza",
        "zibersegurtasun auditoretza",
        "ahultasunen analisia",
        "ahultasunen kudeaketa",
        "intrusio probak",
        "segurtasun eragiketen zentroa",
        "suebakia",
        "identitateen kudeaketa",
        "identitate eta sarbideen kudeaketa",
        "faktore anitzeko autentifikazioa",
        "datuen zifratzea",
        "segurtasun perimetrala",
        "gorabeheren erantzuna",
        "kudeatutako segurtasuna",
        # gl
        "ciberseguridade",
        "seguridade informática",
        "seguridade da información",
        "seguridade dos sistemas de información",
        "esquema nacional de seguridade",
        "adecuación ao ens",
        "auditoría de seguridade",
        "auditoría de ciberseguridade",
        "análise de vulnerabilidades",
        "xestión de vulnerabilidades",
        "probas de intrusión",
        "centro de operacións de seguridade",
        "servizo de soc",
        "servizos de soc",
        "xestión de identidades",
        "xestión de identidades e accesos",
        "seguridade perimetral",
        "resposta a incidentes",
        "concienciación en ciberseguridade",
        "seguridade xestionada",
    ],
    "DATOS_IA": [
        # es
        "business intelligence",
        "inteligencia de negocio",
        "cuadro de mando",
        "cuadros de mando",
        "analítica de datos",
        "analítica avanzada",
        "plataforma de datos",
        "data warehouse",
        "almacén de datos",
        "lago de datos",
        "data lake",
        "big data",
        "ciencia de datos",
        "gobierno del dato",
        "gobernanza del dato",
        "calidad del dato",
        "datos abiertos",
        "portal de datos abiertos",
        "inteligencia artificial",
        "ia generativa",
        "aprendizaje automático",
        "machine learning",
        "aprendizaje profundo",
        "deep learning",
        "procesamiento de lenguaje natural",
        "procesamiento del lenguaje natural",
        "modelos de lenguaje",
        "modelo predictivo",
        "modelos predictivos",
        "minería de datos",
        "visualización de datos",
        "asistente virtual",
        "chatbot",
        "visión artificial",
        # ca
        "intel·ligència de negoci",
        "quadre de comandament",
        "quadres de comandament",
        "analítica de dades",
        "analítica avançada",
        "plataforma de dades",
        "magatzem de dades",
        "llac de dades",
        "ciència de dades",
        "govern de la dada",
        "governança de la dada",
        "qualitat de la dada",
        "dades obertes",
        "portal de dades obertes",
        "intel·ligència artificial",
        "aprenentatge automàtic",
        "aprenentatge profund",
        "processament del llenguatge natural",
        "models de llenguatge",
        "model predictiu",
        "models predictius",
        "mineria de dades",
        "visualització de dades",
        "assistent virtual",
        "visió artificial",
        # eu
        "negozio adimena",
        "aginte koadroa",
        "aginte koadroak",
        "datuen analitika",
        "analitika aurreratua",
        "datu plataforma",
        "datu biltegia",
        "datu lakua",
        "datu zientzia",
        "datuen gobernantza",
        "datuaren gobernantza",
        "datuen kalitatea",
        "datu irekiak",
        "datu irekien ataria",
        "adimen artifiziala",
        "adimen artifizial",
        "ia sortzailea",
        "ikasketa automatikoa",
        "ikasketa sakona",
        "hizkuntza naturalaren prozesamendua",
        "hizkuntza ereduak",
        "eredu prediktiboa",
        "eredu prediktiboak",
        "datu meatzaritza",
        "datuen bistaratzea",
        "laguntzaile birtuala",
        "ikusmen artifiziala",
        # gl
        "intelixencia de negocio",
        "cadro de mando",
        "cadros de mando",
        "goberno do dato",
        "gobernanza do dato",
        "calidade do dato",
        "datos abertos",
        "portal de datos abertos",
        "intelixencia artificial",
        "aprendizaxe automática",
        "aprendizaxe profunda",
        "procesamento da linguaxe natural",
        "modelos de linguaxe",
        "modelo preditivo",
        "modelos preditivos",
    ],
    "DESARROLLO": [
        # es
        "desarrollo de software",
        "desarrollo de aplicaciones",
        "desarrollo a medida",
        "desarrollo de una aplicación",
        "desarrollo web",
        "diseño y desarrollo web",
        "desarrollo de la página web",
        "desarrollo del portal web",
        "desarrollo del sitio web",
        "desarrollo evolutivo",
        "mantenimiento evolutivo",
        "mantenimiento correctivo",
        "mantenimiento adaptativo",
        "mantenimiento de aplicaciones",
        "mantenimiento de software",
        "evolutivos y correctivos",
        "correctivos y evolutivos",
        "factoría de software",
        "fábrica de software",
        "servicios de desarrollo",
        "aplicación web",
        "aplicaciones web",
        "aplicación móvil",
        "aplicaciones móviles",
        "app móvil",
        "apps móviles",
        "api",
        "apis",
        "api rest",
        "microservicios",
        "arquitectura de microservicios",
        "devops",
        "integración continua",
        "desarrollo ágil",
        "metodología ágil",
        "pruebas de software",
        "testing de software",
        "aseguramiento de la calidad del software",
        # ca
        "desenvolupament de programari",
        "desenvolupament d'aplicacions",
        "desenvolupament a mida",
        "desenvolupament d'una aplicació",
        "desenvolupament web",
        "disseny i desenvolupament web",
        "desenvolupament de la pàgina web",
        "desenvolupament del portal web",
        "desenvolupament del lloc web",
        "desenvolupament evolutiu",
        "manteniment evolutiu",
        "manteniment correctiu",
        "manteniment adaptatiu",
        "manteniment d'aplicacions",
        "manteniment de programari",
        "evolutius i correctius",
        "correctius i evolutius",
        "factoria de programari",
        "fàbrica de programari",
        "serveis de desenvolupament",
        "aplicació web",
        "aplicacions web",
        "aplicació mòbil",
        "aplicacions mòbils",
        "app mòbil",
        "microserveis",
        "arquitectura de microserveis",
        "integració contínua",
        "desenvolupament àgil",
        "metodologia àgil",
        "proves de programari",
        # eu
        "software garapena",
        "software garapen",
        "softwarearen garapena",
        "aplikazioen garapena",
        "neurrira egindako garapena",
        "aplikazio baten garapena",
        "web garapena",
        "web diseinua eta garapena",
        "web orriaren garapena",
        "web atariaren garapena",
        "webgunearen garapena",
        "garapen ebolutiboa",
        "mantentze ebolutiboa",
        "mantentze zuzentzailea",
        "mantentze egokitzailea",
        "aplikazioen mantentzea",
        "softwarearen mantentzea",
        "software faktoria",
        "garapen zerbitzuak",
        "web aplikazioa",
        "web aplikazioak",
        "aplikazio mugikorra",
        "aplikazio mugikorrak",
        "mugikorretarako aplikazioa",
        "mikrozerbitzuak",
        "mikrozerbitzuen arkitektura",
        "integrazio jarraitua",
        "garapen arina",
        "metodologia arina",
        "software probak",
        # gl
        "desenvolvemento de software",
        "desenvolvemento de aplicacións",
        "desenvolvemento á medida",
        "desenvolvemento dunha aplicación",
        "desenvolvemento web",
        "deseño e desenvolvemento web",
        "desenvolvemento da páxina web",
        "desenvolvemento do portal web",
        "desenvolvemento do sitio web",
        "desenvolvemento evolutivo",
        "mantemento evolutivo",
        "mantemento correctivo",
        "mantemento adaptativo",
        "mantemento de aplicacións",
        "mantemento de software",
        "evolutivos e correctivos",
        "correctivos e evolutivos",
        "servizos de desenvolvemento",
        "aplicacións web",
        "aplicación móbil",
        "aplicacións móbiles",
        "app móbil",
        "microservizos",
        "arquitectura de microservizos",
        "desenvolvemento áxil",
        "metodoloxía áxil",
        "probas de software",
    ],
    "GIS": [
        # es
        "sistema de información geográfica",
        "sistemas de información geográfica",
        "gis",
        "webgis",
        "cartografía digital",
        "geoportal",
        "infraestructura de datos espaciales",
        "datos geoespaciales",
        "información geoespacial",
        "geolocalización",
        "georreferenciación",
        "visor cartográfico",
        "visor geográfico",
        "callejero digital",
        "arcgis",
        "qgis",
        "esri",
        "geoserver",
        # ca
        "sistema d'informació geogràfica",
        "sistemes d'informació geogràfica",
        "cartografia digital",
        "infraestructura de dades espacials",
        "dades geoespacials",
        "informació geoespacial",
        "geolocalització",
        "georeferenciació",
        "visor cartogràfic",
        "visor geogràfic",
        "carrerer digital",
        # eu
        "informazio geografikoko sistema",
        "informazio geografikoko sistemak",
        "kartografia digitala",
        "geoportala",
        "datu espazialen azpiegitura",
        "datu geoespazialak",
        "informazio geoespaziala",
        "geolokalizazioa",
        "georreferentziazioa",
        "ikustaile kartografikoa",
        "ikustaile geografikoa",
        # gl
        "sistema de información xeográfica",
        "sistemas de información xeográfica",
        "cartografía dixital",
        "infraestrutura de datos espaciais",
        "datos xeoespaciais",
        "información xeoespacial",
        "xeolocalización",
        "xeorreferenciación",
        "visor xeográfico",
        "rueiro dixital",
    ],
    "SANIDAD_DIGITAL": [
        # es
        "historia clínica electrónica",
        "historia clínica digital",
        "historia clínica informatizada",
        "historia de salud electrónica",
        "receta electrónica",
        "prescripción electrónica",
        "sistema de información hospitalaria",
        "sistema de información sanitaria",
        "sistema de información clínica",
        "sistema his",
        "his/pacs",
        "pacs",
        "ris/pacs",
        "ris-pacs",
        "imagen médica digital",
        "telemedicina",
        "teleconsulta",
        "telemonitorización",
        "salud digital",
        "sanidad digital",
        "carpeta de salud",
        "carpeta personal de salud",
        "sistema de cita previa",
        "gestión de pacientes",
        "sistema de gestión de pacientes",
        "interoperabilidad sanitaria",
        "estación clínica",
        "software sanitario",
        "software clínico",
        # ca
        "història clínica electrònica",
        "història clínica digital",
        "història clínica informatitzada",
        "història de salut electrònica",
        "recepta electrònica",
        "prescripció electrònica",
        "sistema d'informació hospitalària",
        "sistema d'informació sanitària",
        "sistema d'informació clínica",
        "imatge mèdica digital",
        "telemonitoratge",
        "salut digital",
        "sanitat digital",
        "carpeta de salut",
        "carpeta personal de salut",
        "sistema de cita prèvia",
        "gestió de pacients",
        "sistema de gestió de pacients",
        "interoperabilitat sanitària",
        "estació clínica",
        "programari sanitari",
        "programari clínic",
        # eu
        "historia kliniko elektronikoa",
        "historia kliniko digitala",
        "historia kliniko informatizatua",
        "osasun historia elektronikoa",
        "errezeta elektronikoa",
        "preskripzio elektronikoa",
        "ospitaleko informazio sistema",
        "osasun informazio sistema",
        "informazio klinikoko sistema",
        "irudi mediko digitala",
        "telemedikuntza",
        "telekontsulta",
        "telemonitorizazioa",
        "osasun digitala",
        "osasun karpeta",
        "osasun karpeta pertsonala",
        "aurretiko hitzordu sistema",
        "pazienteen kudeaketa",
        "pazienteen kudeaketa sistema",
        "osasun elkarreragingarritasuna",
        "estazio klinikoa",
        "osasun softwarea",
        "software klinikoa",
        # gl
        "historia clínica dixital",
        "historia de saúde electrónica",
        "receita electrónica",
        "prescrición electrónica",
        "imaxe médica dixital",
        "saúde dixital",
        "sanidade dixital",
        "carpeta de saúde",
        "carpeta persoal de saúde",
        "xestión de pacientes",
        "sistema de xestión de pacientes",
        "interoperabilidade sanitaria",
    ],
    "ADMIN_ELECTRONICA": [
        # es
        "administración electrónica",
        "e-administración",
        "administración digital",
        "sede electrónica",
        "tramitación electrónica",
        "tramitador electrónico",
        "registro electrónico",
        "firma electrónica",
        "firma digital",
        "certificado digital",
        "portafirmas",
        "portafirmas electrónico",
        "cl@ve",
        "interoperabilidad",
        "plataforma de interoperabilidad",
        "esquema nacional de interoperabilidad",
        "gestor de expedientes",
        "gestión de expedientes",
        "expediente electrónico",
        "archivo electrónico",
        "notificación electrónica",
        "notificaciones electrónicas",
        "carpeta ciudadana",
        "portal de transparencia",
        "portal del ciudadano",
        "licitación electrónica",
        "contratación electrónica",
        "factura electrónica",
        "facturación electrónica",
        # ca
        "administració electrònica",
        "administració digital",
        "seu electrònica",
        "tramitació electrònica",
        "tramitador electrònic",
        "registre electrònic",
        "signatura electrònica",
        "signatura digital",
        "certificat digital",
        "portasignatures",
        "interoperabilitat",
        "plataforma d'interoperabilitat",
        "esquema nacional d'interoperabilitat",
        "gestor d'expedients",
        "gestió d'expedients",
        "expedient electrònic",
        "arxiu electrònic",
        "notificació electrònica",
        "notificacions electròniques",
        "carpeta ciutadana",
        "portal de transparència",
        "portal del ciutadà",
        "licitació electrònica",
        "contractació electrònica",
        "factura electrònica",
        "facturació electrònica",
        # eu
        "administrazio elektronikoa",
        "administrazio elektroniko",
        "administrazio digitala",
        "egoitza elektronikoa",
        "egoitza elektroniko",
        "izapidetze elektronikoa",
        "izapidetzaile elektronikoa",
        "erregistro elektronikoa",
        "sinadura elektronikoa",
        "sinadura digitala",
        "ziurtagiri digitala",
        "elkarreragingarritasuna",
        "elkarreragingarritasun plataforma",
        "elkarreragingarritasun eskema nazionala",
        "espedienteen kudeatzailea",
        "espedienteen kudeaketa",
        "espediente elektronikoa",
        "dokumentu kudeatzailea",
        "dokumentu kudeaketa sistema",
        "artxibo elektronikoa",
        "jakinarazpen elektronikoa",
        "jakinarazpen elektronikoak",
        "herritarren karpeta",
        "gardentasun ataria",
        "herritarraren ataria",
        "lizitazio elektronikoa",
        "kontratazio elektronikoa",
        "faktura elektronikoa",
        "fakturazio elektronikoa",
        # gl
        "administración dixital",
        "rexistro electrónico",
        "sinatura electrónica",
        "sinatura dixital",
        "certificado dixital",
        "portasinaturas",
        "interoperabilidade",
        "plataforma de interoperabilidade",
        "esquema nacional de interoperabilidade",
        "xestor de expedientes",
        "xestión de expedientes",
        "arquivo electrónico",
        "notificacións electrónicas",
        "carpeta cidadá",
        "portal do cidadán",
    ],
    # ── Familias de D2 (plan de clasificación en tres niveles, 2026-09-27) ──
    "RRHH_NOMINA": [
        # Movidas desde ERP: una nómina no es un ERP, y quien las busca no
        # quiere que se le mezclen con la gestión económico-financiera.
        "sistema de nóminas",
        "software de nóminas",
        "sistema de gestión de recursos humanos",
        "sistema de información de recursos humanos",
        "sistema de nòmines",
        "programari de nòmines",
        "sistema de gestió de recursos humans",
        "nominen sistema",
        "nominen softwarea",
        "sistema de xestión de recursos humanos",
        # Nuevas: siempre sobre el software, nunca sobre el servicio (la
        # «gestión de nóminas» externalizada es una gestoría, no TI).
        "aplicación de nóminas",
        "aplicació de nòmines",
        "portal del empleado",
        "portal de l'empleat",
        "portal do empregado",
        "software de recursos humanos",
        "programari de recursos humans",
        "giza baliabideen kudeaketa",
    ],
    "GESTION_DOCUMENTAL": [
        # Movidas desde ADMIN_ELECTRONICA.
        "gestor documental",
        "sistema de gestión documental",
        "sistema de gestió documental",
        "xestor documental",
        "sistema de xestión documental",
        # Nuevas. «gestión documental» a secas no: es también la custodia de
        # archivos en papel.
        "software de gestión documental",
        "programari de gestió documental",
        "plataforma de gestión documental",
        "plataforma de gestió documental",
        "gestión de contenidos empresariales",
        "alfresco",
        "nuxeo",
        "dokumentu-kudeaketa",
    ],
    "PUESTO_TRABAJO": [
        # Hardware y soporte del usuario. Ni «puesto de trabajo» (es también el
        # puesto de la plantilla) ni «ofimática» a secas (casa con cursos, que
        # D1 deja fuera de TI).
        "ordenadores personales",
        "ordenadores de sobremesa",
        "ordenadores portátiles",
        "equipos informáticos",
        "material informático",
        "microinformática",
        "soporte microinformático",
        "centro de atención a usuarios",
        "soporte a usuarios",
        "service desk",
        "help desk",
        "licencias de ofimática",
        "paquete ofimático",
        "suite ofimática",
        "ordinadors personals",
        "ordinadors portàtils",
        "equips informàtics",
        "material informàtic",
        "microinformàtica",
        "centre d'atenció a l'usuari",
        "llicències d'ofimàtica",
        "ordenadores persoais",
        "ordenagailu eramangarriak",
        "ekipamendu informatikoa",
    ],
}

# Lista canónica de etiquetas de tecnología (orden estable por inserción del dict).
# Consumida por ``scraper.tech_classifier`` para construir el matriz de labels
# y por la persistencia de scores en ``licitacion_tecnologia_score``.
TECH_LABELS: list[str] = list(TECHNOLOGY_KEYWORDS.keys())

# Etiqueta legible de cada label, para la UI y la analítica. Es la única copia:
# ``services.classification.TECHNOLOGY_LABELS`` se deriva de aquí. Los textos de
# los fabricantes son los históricos y no se tocan — la analítica por tecnología
# agrupa por esta etiqueta (``services/analytics/tecnologias.py``) y cambiarlos
# partiría sus series igual que cambiar el diccionario.
TECH_CATEGORIAS: dict[str, str] = {
    "SAP": "SAP",
    "SALESFORCE": "Salesforce",
    "ORACLE": "Oracle",
    "MICROSOFT": "Microsoft Dynamics / Azure",
    "SERVICENOW": "ServiceNow",
    "WORKDAY": "Workday",
    "IBM": "IBM",
    "OPENTEXT": "OpenText",
    "UNIT4": "Unit4",
    "META4": "Meta4",
    "SOPRA": "Sopra",
    "SAGE": "Sage",
    "INFOR": "Infor",
    "ERP": "ERP (genérico)",
    "CRM": "CRM (genérico)",
    "CLOUD_INFRA": "Infraestructura, cloud y redes",
    "CIBERSEGURIDAD": "Ciberseguridad",
    "DATOS_IA": "Datos e IA",
    "DESARROLLO": "Desarrollo de software",
    "GIS": "GIS y geoinformación",
    "SANIDAD_DIGITAL": "Sanidad digital",
    "ADMIN_ELECTRONICA": "Administración electrónica",
    "RRHH_NOMINA": "RRHH y nómina",
    "GESTION_DOCUMENTAL": "Gestión documental",
    "PUESTO_TRABAJO": "Puesto de trabajo y soporte",
}

TipoLabel = Literal["fabricante", "categoria"]

# Qué es cada label. Un fabricante nombra a un vendor; una categoría nombra qué
# se compra sin decir de quién. Todo consumidor que necesite distinguirlas
# (UI, docs) pregunta aquí y no infiere nada del nombre.
TECH_LABEL_TIPO: dict[str, TipoLabel] = {
    "SAP": "fabricante",
    "SALESFORCE": "fabricante",
    "ORACLE": "fabricante",
    "MICROSOFT": "fabricante",
    "SERVICENOW": "fabricante",
    "WORKDAY": "fabricante",
    "IBM": "fabricante",
    "OPENTEXT": "fabricante",
    "UNIT4": "fabricante",
    "META4": "fabricante",
    "SOPRA": "fabricante",
    "SAGE": "fabricante",
    "INFOR": "fabricante",
    "ERP": "categoria",
    "CRM": "categoria",
    "CLOUD_INFRA": "categoria",
    "CIBERSEGURIDAD": "categoria",
    "DATOS_IA": "categoria",
    "DESARROLLO": "categoria",
    "GIS": "categoria",
    "SANIDAD_DIGITAL": "categoria",
    "ADMIN_ELECTRONICA": "categoria",
    "RRHH_NOMINA": "categoria",
    "GESTION_DOCUMENTAL": "categoria",
    "PUESTO_TRABAJO": "categoria",
}

# Qué cubre cada label, en una frase. Viaja en la pregunta del etiquetado por LLM
# (``services.llm_tech_labeling.build_question``): con solo el nombre, el
# modelo lee «DESARROLLO» como desarrollo nuevo y deja sin etiqueta el
# mantenimiento de una aplicación a medida, que sus keywords sí cubren. Cada
# definición resume su lista de ``TECHNOLOGY_KEYWORDS`` y la tabla de
# ``docs/taxonomia-tecnologica.md``; si una cambia, cambian las tres. Los
# fabricantes se definen por sus productos: el anuncio tiene que nombrarlos.
TECH_DEFINICIONES: dict[str, str] = {
    "SAP": (
        "Productos de SAP: S/4HANA, ECC y sus módulos (FI/CO, MM, SD, HCM…), BW, "
        "BusinessObjects, BTP, SuccessFactors, Ariba o Concur."
    ),
    "SALESFORCE": (
        "Plataforma Salesforce: Sales, Service o Marketing Cloud, MuleSoft, Tableau CRM, Heroku."
    ),
    "ORACLE": (
        "Productos de Oracle: base de datos, E-Business Suite, Fusion, PeopleSoft, "
        "JD Edwards, NetSuite, WebLogic, Siebel, PL/SQL."
    ),
    "MICROSOFT": (
        "Microsoft como plataforma: Dynamics 365 (NAV, AX, Business Central), Power "
        "Platform y Power BI, Azure, SharePoint, SQL Server, .NET, licencias Microsoft 365."
    ),
    "SERVICENOW": "Plataforma ServiceNow: ITSM, ITOM, HRSD o CSM.",
    "WORKDAY": "Workday: HCM, Financials, Adaptive Planning o Prism.",
    "IBM": (
        "Productos de IBM: Maximo, Cognos, WebSphere, DB2, FileNet, Watson, IBM Cloud, "
        "AS/400 o iSeries, Lotus Notes."
    ),
    "OPENTEXT": "Gestión documental y ECM de OpenText: Documentum, Content Server, Extended ECM.",
    "UNIT4": "ERP de Unit4: Agresso, Unit4 Financials.",
    "META4": "Nóminas y RRHH de Meta4 (PeopleNet); también Cezanne HR.",
    "SOPRA": (
        "Soluciones de Sopra: Sopra HR (HR Access) y Sopra Banking; también Sopra Steria "
        "nombrada en el anuncio."
    ),
    "SAGE": "ERP de Sage: X3, 200, 50, Murano o Despachos.",
    "INFOR": "ERP de Infor: LN, M3, CloudSuite, Infor OS o Baan.",
    "ERP": (
        "Sistema de gestión integrado sin fabricante nombrado: gestión "
        "económico-financiera, contabilidad presupuestaria o gestión tributaria."
    ),
    "CRM": (
        "Relación con clientes o ciudadanía sin fabricante nombrado: CRM, plataforma de "
        "atención ciudadana, contact center, automatización de marketing."
    ),
    "CLOUD_INFRA": (
        "Nube (IaaS, PaaS, SaaS), contenedores, virtualización, CPD, hosting, "
        "almacenamiento, copias de seguridad, servidores y redes de datos "
        "(electrónica de red, cableado estructurado, wifi)."
    ),
    "CIBERSEGURIDAD": (
        "Seguridad de la información: ENS, SOC, SIEM, EDR, cortafuegos, auditorías de "
        "seguridad, pentest, gestión de identidades, respuesta a incidentes."
    ),
    "DATOS_IA": (
        "BI y cuadros de mando, data warehouse o data lake, big data, datos abiertos, "
        "inteligencia artificial, aprendizaje automático, chatbots, visión artificial."
    ),
    "DESARROLLO": (
        "Software a medida: su desarrollo y su mantenimiento evolutivo, correctivo o "
        "adaptativo; aplicaciones web o móviles, APIs, microservicios, factoría de "
        "software, DevOps, pruebas."
    ),
    "GIS": (
        "Información geográfica: SIG/GIS, IDE, geoportal, visores cartográficos, "
        "cartografía digital, georreferenciación."
    ),
    "SANIDAD_DIGITAL": (
        "Sistemas de información sanitaria: historia clínica y receta electrónicas, "
        "HIS, PACS, telemedicina, cita previa, gestión de pacientes."
    ),
    "ADMIN_ELECTRONICA": (
        "Administración electrónica: sede, registro y firma electrónicos, "
        "tramitación, gestor de expedientes, archivo electrónico, "
        "interoperabilidad, notificaciones, factura electrónica."
    ),
    "RRHH_NOMINA": (
        "Software de recursos humanos y nómina sin fabricante nombrado: sistema o "
        "aplicación de nóminas, gestión de recursos humanos, portal del empleado."
    ),
    "GESTION_DOCUMENTAL": (
        "Gestión documental y de contenidos sin fabricante nombrado: gestor "
        "documental, sistema o plataforma de gestión documental, ECM, Alfresco o Nuxeo."
    ),
    "PUESTO_TRABAJO": (
        "Puesto de trabajo del usuario: ordenadores de sobremesa y portátiles, "
        "equipos y material informático, microinformática, centro de atención a "
        "usuarios (CAU), service desk, ofimática."
    ),
}

# Los cuatro mapas describen el mismo conjunto: un label sin etiqueta legible,
# sin tipo o sin definición se rompería en la UI o llegaría al LLM sin acotar
# sin que ningún test de dominio lo viera. Se comprueba al importar (y no solo
# en tests) porque la semilla se vuelca en base de datos: un label huérfano aquí
# sería un label huérfano en producción.
if not (set(TECH_CATEGORIAS) == set(TECH_LABELS) == set(TECH_LABEL_TIPO) == set(TECH_DEFINICIONES)):
    raise ValueError(
        "TECHNOLOGY_KEYWORDS, TECH_CATEGORIAS, TECH_LABEL_TIPO y TECH_DEFINICIONES deben "
        "declarar los mismos labels"
    )


# ── Límites de palabra para keywords que no empiezan (o acaban) en letra ────
#
# El patrón de siempre era ``\b(kw1|kw2|...)\b``, y con él **`.net` no puede
# casar nunca**: `\b` antes de un punto exige un carácter de palabra pegado, así
# que `\b\.net` sólo casa dentro de otra palabra (`asp.net`) y jamás en
# «plataforma .NET», que es como aparece en los pliegos. La keyword estaba en el
# diccionario desde su primera versión y no clasificaba nada; sólo se vio al
# escribir el test que compila cada término.
#
# Lo mismo le pasaría, del otro lado, a `c++` o a `c#`: `\b` después de `+` o
# `#` no casa detrás de un espacio.
#
# La regla es la misma de antes donde antes servía —letra pegada a letra— y se
# relaja sólo en el extremo donde el término no empieza ni acaba en carácter de
# palabra. El punto se excluye a la izquierda a propósito: así `.net` sigue sin
# casar dentro de `asp.net`, que es un producto distinto con su propia entrada.
#
# ── Cómo se escribe un título de verdad (2026-09-27) ────────────────────────
#
# Medido ese día en producción: el 16 % de los títulos de PSCP va en mayúsculas
# y sin tildes, y el diccionario escribe con tildes. Con el patrón literal,
# «ADMINISTRACION ELECTRONICA» no casaba con «administración electrónica», ni
# «firewalls» con «firewall», ni «copia  de\nseguridad» (doble espacio, salto
# de línea del XML) con «copia de seguridad». Ahora cada keyword se pliega (sin
# tildes) y se compila con las variantes de cada letra, un plural opcional por
# palabra y separadores tolerantes. El patrón sigue casando sobre el texto tal
# cual llega: ningún consumidor tiene que plegar nada antes de llamar a
# `search`, y el test que compila cada keyword contra sí misma sigue valiendo.

#: Versión de la forma de casar. Entra en el hash de `filter_version`
#: (`services.tecnologias_diccionario._hash_de`): dos filas filtradas con el
#: mismo diccionario pero con matchers distintos no se filtraron igual, y el
#: linaje tiene que poder decirlo. Se cambia a mano cuando cambia `con_limites`.
VERSION_MATCHER = "2026-09-27-plegado-plurales"

#: Letras que un título escribe con o sin diacrítico. La keyword se pliega
#: antes, y cada una de estas letras se convierte en la clase con sus variantes.
_VARIANTES: dict[str, str] = {
    "a": "[aàáâäã]",
    "e": "[eèéêë]",
    "i": "[iìíîï]",
    "o": "[oòóôöõ]",
    "u": "[uùúûü]",
    "n": "[nñ]",
    "c": "[cç]",
}

#: Separadores que en un título real valen lo mismo que el de la keyword.
_SEPARADORES: dict[str, str] = {
    # Dobles espacios y saltos de línea del XML.
    " ": r"\s+",
    # «económico-financiera» y «económico financiera».
    "-": r"[\s\-]?",
    # El apóstrofo recto del diccionario y los tipográficos de los títulos.
    "'": "['\u2019\u2018\u02bc\u00b4`]",
    # «intel·ligència», «intel.ligència» e «intelligència» (el guion, al final de la clase, es literal).
    "\u00b7": "[\u00b7.-]?",
}

#: Plural opcional al final de cada palabra de tres letras o más: «firewalls»,
#: «servidores», «copias de seguridad», «sedes electrónicas». Las palabras más
#: cortas (de, la, el, y, i) no lo llevan: «des» o «les» no son su plural.
_PLURAL = "(?:e?s)?"
_MIN_LETRAS_PLURAL = 3

#: Un patrón que no casa con nada: lo que compila una lista sin keywords. Un
#: `re.compile("")` casaría con cualquier texto y metería el censo entero.
_NUNCA = "(?!)"


def plegar(texto: str) -> str:
    """Quita los diacríticos: «Administración» → «Administracion»."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _cuerpo(keyword: str) -> str:
    """El centro del patrón: letras con sus variantes, separadores y plurales."""
    partes: list[str] = []
    letras_seguidas = 0
    for signo in plegar(keyword):
        if signo.isalpha():
            letras_seguidas += 1
            partes.append(_VARIANTES.get(signo.lower(), re.escape(signo)))
            continue
        if signo in (" ", "-") and letras_seguidas >= _MIN_LETRAS_PLURAL:
            partes.append(_PLURAL)
        letras_seguidas = 0
        partes.append(_SEPARADORES.get(signo, re.escape(signo)))
    if letras_seguidas >= _MIN_LETRAS_PLURAL:
        partes.append(_PLURAL)
    return "".join(partes)


def con_limites(keyword: str) -> str:
    """Fragmento de regex para ``keyword`` con el límite correcto a cada lado."""
    izquierda = r"\b" if keyword[:1].isalnum() or keyword[:1] == "_" else r"(?<![\w.])"
    derecha = r"\b" if keyword[-1:].isalnum() or keyword[-1:] == "_" else r"(?!\w)"
    return f"{izquierda}{_cuerpo(keyword)}{derecha}"


def patron_de_keywords(keywords: Iterable[str], *, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    """Regex que casa cualquiera de ``keywords``, cada una con sus límites.

    Fuente única del criterio: `services/tecnologias_diccionario.patrones`,
    `scraper/filters` y los tests compilan por aquí, de modo que arreglar un
    caso como `.net` lo arregla en los tres a la vez.

    Las keywords van de la más larga a la más corta: la alternancia se queda
    con la primera que casa en cada posición, y así «SAP FI/CO» es `sap fi/co`
    y no `sap` (que es lo que devuelve `findall`, p. ej. para la señal de
    pliegos). Qué keywords **están** en un texto lo dice
    :func:`keywords_presentes`, que no depende de ese orden.
    """
    unicas = [k for k in dict.fromkeys(keywords) if k]
    if not unicas:
        return re.compile(_NUNCA)
    ordenadas = sorted(unicas, key=lambda k: len(plegar(k)), reverse=True)
    return re.compile("|".join(con_limites(k) for k in ordenadas), flags=flags)


@functools.lru_cache(maxsize=8192)
def patron_de_keyword(keyword: str) -> re.Pattern[str]:
    """El patrón de una sola keyword, memoizado: lo piden a cada texto."""
    return patron_de_keywords([keyword])


def keywords_presentes(textos: Iterable[str | None], keywords: Iterable[str]) -> list[str]:
    """Las keywords que aparecen en alguno de los textos, en su forma canónica.

    Forma canónica es la del diccionario en minúsculas, no la del texto: la
    puerta de PSCP compara lo casado con `KEYWORDS_AMBIGUAS`, y si volviera
    «gestio» o «firewalls» ninguna ambigua se reconocería. Y son **todas** las
    que aparecen, no la primera de la alternancia: con esa, «Suport SAP FI/CO i
    SAP MM» se quedaba en `sap`, que es ambigua.
    """
    normalizados = [unicodedata.normalize("NFC", t) for t in textos if t]
    if not normalizados:
        return []
    presentes = {
        kw.lower()
        for kw in keywords
        if kw and any(patron_de_keyword(kw).search(t) for t in normalizados)
    }
    return sorted(presentes)
