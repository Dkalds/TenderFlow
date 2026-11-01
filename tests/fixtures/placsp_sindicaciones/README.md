# Fixtures de las sindicaciones 1143, 1044 y 1403 de PLACSP

Las consumen `tests/test_connectors_placsp_sindicaciones.py` (1143 y 1044) y
`tests/test_connectors_placsp_consultas.py` (1403).

| Fichero | Feed | Entradas |
|---|---|---|
| `contratos_menores_1143.atom` | `sindicacion_1143/contratosMenoresPerfilesContratantes.atom` — contratos menores de los perfiles alojados en PLACSP | 6 |
| `agregadas_1044.atom` | `sindicacion_1044/PlataformasAgregadasSinMenores.atom` — licitaciones que las plataformas autonómicas vierten en PLACSP por agregación, sin menores | 5 |
| `consultas_1403.atom` | `sindicacion_1403/CPM_SectorPublico.atom` — consultas preliminares de mercado (bajada el 2026-10-31, mismo recorte) | 5 |

## Son recortes reales

Bajados el 2026-10-24 con `GET` a la URL documentada de cada sindicación (el
primer fichero y los siguientes por `rel="next"`) y recortados por
un script de un solo uso a unas pocas entradas, **sin tocar su contenido** salvo
dos cosas:

- Se quitan los bloques `cac:Contact` (teléfono, correo y nombre de la persona de
  contacto de cada órgano).
- Las cabeceras conservan solo dos de las `at:deleted-entry` (tombstones) del
  feed de menores, para que el formato real esté a la vista.

No hay adjudicatarios personas físicas: se eligieron entradas cuyos
adjudicatarios son sociedades. El NIF enmascarado de la tercera entrada de
menores (`****2061*`, una SL) es como lo publica PLACSP.

Qué hay en cada entrada (la posición importa a los tests):

**`contratos_menores_1143.atom`**

| # | Entrada | Para qué |
|---|---|---|
| 0 | Desarrollo evolutivo (Subdirección General de Contratación) | Admitida por keyword, con adjudicatario |
| 1 | Suscripción de Gartner (Subsecretaría de Política Territorial) | Admitida por CPV 72 |
| 2 | Mantenimiento y soporte (Ayuntamiento de Madrid) | Adjudicataria con NIF enmascarado |
| 3 | Ortoprótesis (FREMAP) | Sin señal tecnológica |
| 4, 5 | `1/2026` de dos órganos distintos | Mismo `ContractFolderID`, órganos y adjudicatarios distintos: la colisión de claves |

**`agregadas_1044.atom`**

| # | Entrada | Para qué |
|---|---|---|
| 0 | Equipos informáticos (Mercados de Abastecimientos de Barcelona) | Adjudicada, pliegos en `contractaciopublica.cat` |
| 1 | Desarrollo (Ajuntament de Blanes) | Abierta, plazo 2026-11-09, pliegos en `contractaciopublica.cat` |
| 2 | Consultoría ENS (Ayuntamiento de Bilbao) | Pliegos en `contratacion.euskadi.eus` (fuera de la allowlist) |
| 3 | Mantenimiento de aplicaciones (Dirección General de Infraestructuras) | Abierta, 3 lotes |
| 4 | Parques infantiles (Tudela) | Sin señal tecnológica |

**`consultas_1403.atom`**

| # | Entrada | Para qué |
|---|---|---|
| 0 | Servicios de ciberseguridad (GESPLAN, Canarias) | Admitida por keyword, sin CPV; plazo de respuesta 2026-11-10 |
| 1 | Sistema de gestión tributaria (ATRM, Murcia) | CPV 72; su identificador, `1/2026`, lo usan otros tres órganos en el feed |
| 2 | Aplicación de gestión documental (Boadilla) | Estado `REA` (realizada) |
| 3 | Microscopio electrónico (CSIC) | Sin señal en el objeto; solo el párrafo de la consulta casaba con una keyword |
| 4 | Plantas de agua | Sin señal tecnológica |

Las direcciones de correo que quedan en la de la ATRM y en la cabecera son
buzones institucionales, no de personas.

Todas las entradas admitidas lo son por keyword o por CPV (deterministas); ninguna
depende del rescate por clasificador ML.

## Qué se midió con el feed completo (2026-10-24)

El análisis de identidad de menores y el reparto de hosts de los pliegos de las
agregadas están en el docstring de `scraper/connectors/placsp_menores.py` y
`placsp_agregadas.py`, y las cifras en el backlog.

## Caducan en una cosa

El plazo de la entrada 1 de agregadas (2026-11-09) y de la 3 (2026-11-06) pasará.
Los tests no dependen de «hoy»: el recorrido de Radar fija `hoy_iso="2026-10-24"`.
