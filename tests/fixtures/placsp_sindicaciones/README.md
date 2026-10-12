# Fixtures de las sindicaciones 1143 y 1044 de PLACSP

Las consumen `tests/test_connectors_placsp_sindicaciones.py`.

| Fichero | Feed que imita |
|---|---|
| `contratos_menores_1143.atom` | `sindicacion_1143/contratosMenoresPerfilesContratantes.atom` — contratos menores de los perfiles alojados en PLACSP |
| `agregadas_1044.atom` | `sindicacion_1044/PlataformasAgregadasSinMenores.atom` — licitaciones que las plataformas autonómicas vierten en PLACSP por agregación, sin menores |

## Son sintéticas

**Ninguna entrada es un expediente real.** La sesión que las escribió
(2026-10-12) no tenía salida a `contrataciondelsectorpublico.gob.es` ni a
`contrataciondelestado.es` (el proxy de la sesión denegaba el `CONNECT`), así que
no pudo descargar una muestra. Están construidas a partir de lo documentado: la
página de datos abiertos del Ministerio de Hacienda describe el mismo ATOM
paginado para las tres sindicaciones (500 entradas por fichero como máximo y el
resto enlazado con `rel="next"`), y el contenido de cada entrada se **asume**
igual al del feed principal `sindicacion_643`: CODICE (`ContractFolderStatus`).
Esa suposición es justo lo que hay que verificar con una muestra real. Los órganos
(«Villaejemplo», «Servicio Regional de Ejemplo»), los adjudicatarios y sus NIF
son inventados a propósito para que nadie los lea como datos.

Lo que cada entrada fija está comentado dentro del propio fichero. Dos rarezas
deliberadas:

- La cuarta entrada de menores no trae `ContractFolderStatusCode` y sí un plazo
  de presentación (2099). Un contrato menor no tiene ninguna de las dos cosas;
  está para comprobar que el conector lo guarda cerrado y sin plazo pase lo que
  pase, porque es lo que lo mantiene fuera del Radar.
- Los plazos de las convocatorias agregadas están en 2099 para que la prueba de
  «aparece en el Radar» no caduque.

Sustituirlas por un recorte real es lo primero que hay que hacer al activar
cualquiera de las dos fuentes: `python -m scraper.connectors.placsp_menores
--check --dump muestra.atom` (y lo mismo con `placsp_agregadas`) guarda la
primera página tal como llega.
