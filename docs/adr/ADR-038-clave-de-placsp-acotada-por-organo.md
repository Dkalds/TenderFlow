---
id: ADR-038
title: "El id_externo de una fuente cuyo expediente no es único entre órganos se acota por el órgano: PLACSP pasa a placsp:<órgano>:<expediente>"
status: accepted
date: 2026-10-26
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-009-framework-conectores-multifuente]]"
  - "[[ADR-026-caminos-de-lectura-y-precedencia-tecnologica]]"
  - "[[ADR-032-semantica-del-importe-y-maestro-de-organos]]"
tags: [adr]
---

# ADR-038 — El `id_externo` se acota por el órgano cuando el expediente no es único entre órganos

- **Estado:** aceptado
- **Fecha:** 2026-10-26
- **Revisa:** el *Rationale* de
  [ADR-009](ADR-009-framework-conectores-multifuente.md) («las filas PLACSP
  existentes no se migran: conservan su expediente crudo»; migrar las PK a
  `placsp:...` era «alto riesgo sin beneficio»). El resto de ADR-009 —el
  contrato `Connector`, el runner genérico y el prefijo `<fuente>:` de las
  fuentes nuevas— sigue vigente.
- **Implementa:** el RFC
  [2026-10-24-rfc-identidad-placsp-organo-expediente](../rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md)
  (`approved`), fases A (`v163_identidad_placsp_fase_a`) y B
  (`v164_identidad_placsp_rekey`).

---

## Contexto

ADR-009 dejó las filas de PLACSP con el `ContractFolderID` sin prefijo como
`id_externo`, que es la clave primaria de `licitaciones`, porque el prefijo
solo hacía falta para que las fuentes nuevas no chocaran con PLACSP. Daba por
hecho algo que no es verdad: que el número de expediente es único dentro de
PLACSP. Lo teclea cada órgano («1681/2026», «2026/LIC/0049») y se repite entre
órganos: en el feed vivo, 94 de 4.518 `ContractFolderID` los usan dos o más
órganos (2,1 %). Con `ON CONFLICT(id_externo)`, la segunda licitación
**sustituye** a la primera sin error, y como las adjudicaciones y los documentos
solo se reemplazan cuando la entrada nueva trae los suyos, lo que queda mezcla
las dos (una convocatoria abierta puede aparecer adjudicada a la empresa que
ganó el contrato de otro órgano). El RFC midió en `licitaciones_history` 379
`id_externo` y 570 pares (expediente, órgano perdido) de pisada segura, como
cota inferior.

El mismo defecto ya se había arreglado dos veces fuera de PLACSP: PSCP con
`pscp:<uuid>:<codi_expedient>` (`v153`) y contratos menores con
`placsp_menores:<ID_PLATAFORMA>:<ContractFolderID>`. El «beneficio» que ADR-009
no veía está medido.

## Decisión

1. **Regla general.** El `id_externo` de una fuente cuyo número de expediente
   no es único entre órganos se acota con el identificador del órgano **en esa
   fuente**: `<prefijo>:<órgano>:<expediente>`. Una fuente nueva que cumpla la
   condición nace así; no se espera a medir pisadas.
2. **PLACSP.** `placsp:<ID_PLATAFORMA>:<ContractFolderID>` para el feed vivo y
   el ZIP mensual (el prefijo es de la familia, no del carril: los dos escriben
   la misma fila; `fuente` sigue diciendo `placsp` o `bulk_YYYYMM`), y lo mismo
   para `placsp_watched_company_awards` y `placsp_agregadas` (órgano en
   `ID_OC_PLAT`). Respaldo `NIF` y `DIR3`, contados; sin órgano, la entrada no
   se escribe. `ID_PLATAFORMA` es el único identificador presente en el 100 %
   de las entradas que además es 1:1 con el órgano.
3. **Una sola definición.** `shared/identidad_placsp.py` construye, descompone
   y da el expediente natural de la clave (con su gemelo SQL); los escritores
   pasan por `scraper.codice_parser.acotar_por_organo`. El órgano se codifica
   (`%` → `%25`, `:` → `%3A`) y el expediente va tal cual, así que todo lo que
   sigue al segundo `:` es el expediente.
4. **El expediente natural no cambia.** El dedupe con TED (BT-22), PSCP y
   agregadas sigue casando por el `ContractFolderID`; la clave nueva solo cambia
   la identidad de la fila, no lo que se compara entre fuentes.
5. **Las filas ya escritas se migran** (`v164_identidad_placsp_rekey`: copiar,
   repuntar las 31 columnas que guardan el id, borrar), y cada id viejo queda en
   `licitaciones_id_anterior`. La API lo resuelve con `Deprecation`/`Sunset`
   hasta el 2027-04-30; la ficha pública redirige (308) sin fecha de fin.

## Consecuencias

- **Positivo:** dos órganos con el mismo número de expediente conviven; las
  pisadas dejan de producirse (y `placsp_colision_expediente_total` tiene que
  quedarse en 0). La reingesta de los ZIP recupera las que ya ocurrieron.
- **Positivo:** se pierde la «inconsistencia estética» de ADR-009: todas las
  fuentes llevan prefijo.
- **Negativo:** cambia la identidad de ~24.700 filas y de todo lo que las
  referencia, URLs públicas incluidas. Mitigado con los alias, la 308 y el campo
  aditivo `expediente` de la API (lo que el usuario ve como número de
  expediente no cambia).
- **Negativo:** un receptor de webhooks que correlacione con eventos anteriores
  verá otro id para el mismo expediente; se resuelve por la API hasta el
  *sunset*.
- **Riesgo aceptado:** un órgano que renumere su expediente sigue siendo una
  fila nueva, como antes (RFC, pregunta abierta 3).
- **Para la próxima re-key:** `licitaciones_id_anterior` es genérica
  (`motivo`), y la lista de referencias de `v164` (con `domain_events.aggregate_id`,
  que `v153` olvidó) es el punto de partida; su test falla si aparece una FK
  nueva a `licitaciones`.

## Alternativas descartadas

Las del RFC, §«Alternativas descartadas»: `placsp:<idEvl>` (opaco, saca el
expediente de la clave y agregadas no lo trae), el `<id>` Atom, DIR3 o NIF como
órgano (no son 1:1), el nombre del órgano (los renombres partirían la fila),
la re-key perezosa (dos formatos para siempre y las pisadas sin recuperar), la
clave sustituta entera y el prefijo por carril.
