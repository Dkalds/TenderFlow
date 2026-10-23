# Reencolar documentos cuyo formato ya se lee

Cuándo: cada vez que `scraper/document_fetcher.py` aprende un formato (la
última, 2026-10-23: OpenDocument con la biblioteca estándar y el ZIP
endurecido). **Lo ejecuta el propietario contra producción**: cambia el estado
de filas de producción (AGENTS.md §6).

## Por qué hace falta

`unsupported` es un estado terminal a propósito
(`DocumentosRepository.mark_unsupported`): reintentar con el mismo extractor
daría lo mismo y se comería el lote nocturno. Nada lo saca de ahí solo. Lo
mismo pasa con las filas que, antes de `v103`, caían en `error` con el detalle
`content-type no soportado: …`.

El caso grande es el DOCX que PLACSP mandaba con el tipo mal escrito
(`application/vnd.openxmlformatsofficedocument…`, sin guion): ~2.140 filas
medidas el 2026-10-23 (1.007 `unsupported` y 1.131 `error`), más 48 ODT, 2 ODS
y 215 ZIP. Desde 2026-09-28 el formato lo decide la firma del contenido, así
que esas filas ya se leen en cuanto vuelven a `pending`.

## Qué toca y qué no

`make reencolar-documentos` (`scripts/reencolar_documentos_no_soportados.py`,
SQL en `DocumentosRepository.reencolar_formatos_soportados`) devuelve a
`pending`, con `error_detail` vacío:

- filas `unsupported`, y
- filas `error` cuyo detalle empieza por `content-type no soportado:`,

**solo** si su `content_type` es uno de los que el extractor declara
(`supported_content_types()`), comparado sin guiones ni parámetros. No toca:
XLSX, XML, HTML, RTF, `.doc`, RAR (siguen sin leerse), los PDF cifrados,
escaneados o demasiado largos (su `error` no es de formato) ni las descargas
fallidas (esas las revive el propio lote, `revivir_descargas_fallidas`).

## Pasos

1. Con un `DATABASE_URL` de producción **con permiso de escritura**, contar
   primero (no escribe nada):

   ```bash
   make reencolar-documentos
   ```

   Sale una línea por `(status, content_type)`. Si el total no se parece a lo
   de arriba, parar y mirar por qué antes de seguir.

2. Reencolar:

   ```bash
   make reencolar-documentos APLICAR=1
   # o: python scripts/reencolar_documentos_no_soportados.py --aplicar --json
   ```

3. Comprobar que la siguiente cuenta da 0 (es idempotente) y dejar que el lote
   nocturno de `pliegos.yml` los drene. Van detrás en `list_pendientes`
   (newest-first y sin plazo abierto casi todos), a razón del lote diario, así
   que tardan varias noches. El resumen del job lo cuenta por formato
   (`documentos_por_formato` en `/analytics/quality`).

## Qué esperar

- Muchos DOCX antiguos acabarán en `error` con `descarga fallida:` en vez de
  `extracted`: el token de las URI de PLACSP caduca (~82 % de las antiguas no
  responde). Los que tengan binario guardado (`blob_key`) se extraen del
  almacén sin volver a PLACSP. No es una regresión: es lo que se puede
  recuperar.
- Un ZIP que no contenga nada legible vuelve a `unsupported` con el detalle
  «ZIP sin documentos procesables».
- Un ZIP hostil (ratio de compresión, tamaño por entrada) termina en `error`,
  no en `unsupported`.

## Fuera de alcance

El OCR de escaneados no se amplía con esto: los PDF «sin texto extraíble» no
se reencolan, porque el coste por página del OCR sigue sin medir (S8.3, ítem
S8 de [IMPROVEMENT_BACKLOG.md](../IMPROVEMENT_BACKLOG.md)).
