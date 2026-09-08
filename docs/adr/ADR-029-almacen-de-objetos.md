# ADR-029 — Almacén de objetos para binarios: se revoca «texto por página, sin blob store»

- **Estado:** aceptado
- **Fecha:** 2026-09-06
- **Supersede:** la decisión «texto por página, sin blob store» del plan de
  producto (Pliegos+RAG), que este ADR revoca de forma explícita
- **Relacionado:** [ADR-022](ADR-022-frontera-de-persistencia.md),
  [ADR-016](ADR-016-destino-persistencia-supabase.md),
  [ADR-028](ADR-028-cola-de-trabajo-y-worker.md)
- **Implementa:** S8.1 de
  [docs/plans/2026-09-plan-arquitectura-v2.md](../plans/2026-09-plan-arquitectura-v2.md)

---

## Contexto

El plan de producto decidió guardar **solo texto por página** y no el binario:
el PDF se descarga de PLACSP, se extrae, se guarda `documento_pages` y el
binario se tira. La razón era buena —no pagar almacenamiento por algo que la
fuente ya sirve— y aguantó mientras la extracción fue una sola pasada de
`pdfplumber`.

Lo que la invalida son tres hechos posteriores:

1. **La re-extracción necesita el binario.** Cambiar el extractor, añadir OCR
   (S8.3) o soportar DOCX/ODT/ZIP (S8.2) obliga a volver a descargar de PLACSP
   todo el corpus. La fuente no garantiza permanencia de URL y ya devolvió 404
   sobre documentos ingeridos.
2. **`documentos.source_hash` (`v88`) existe para deduplicar** un binario que
   no se conserva: se calcula el hash de algo que se tira.
3. **Los artefactos de modelo ya necesitan un bucket.**
   `shared/model_artifacts.py` resuelve hoy contra Releases de GitHub, que
   exige token y no es un almacén de objetos.

---

## Decisión

### A. Hay bucket, S3-compatible, y `shared/object_store.py` es su única frontera

Clave `documentos/{source_hash}`; columna `documentos.blob_key`. Implementación
sobre Supabase Storage o Cloudflare R2 —ambos S3-compatibles, y la elección
concreta es de despliegue, no de arquitectura— con `boto3`, ya opcional en
`config/secrets.py`.

Ningún módulo habla con el bucket salvo `shared/object_store.py`. Es la misma
regla que ADR-022 aplica al SQL: un solo estrato conoce el almacén.

### B. Los tests no tocan la red

`shared/object_store.py` expone una implementación sobre sistema de ficheros
que la suite usa siempre. Un test que necesite red para leer un documento es un
test que no corre en CI.

### C. Lo que se guarda tiene plazo

`retention_cleanup` purga binarios de expedientes cerrados hace más de
veinticuatro meses y **cuenta** lo que purga. El plazo vive en
`config/settings.py` como `RETENTION_*` y se publica en
[docs/SECURITY.md](../SECURITY.md) (C9.3 del plan complementario), no como
constante enterrada.

### D. El tamaño del bucket es un número visible

`/analytics/quality` lo expone. Un almacén cuyo coste nadie mira crece hasta
que aparece en la factura.

### E. Los artefactos de modelo usan el mismo bucket

`shared/model_artifacts.py` resuelve **primero** el bucket y después la Release
de GitHub, con el mismo sha256. El fallback se conserva: quita el token de
GitHub del camino crítico sin romper lo que ya funciona.

---

## Consecuencias

**A favor.** La re-extracción deja de depender de que PLACSP siga sirviendo el
documento. OCR y formatos nuevos se aplican al corpus histórico. `source_hash`
pasa a tener sentido. Los modelos dejan de necesitar un token de GitHub.

**En contra.** Coste de almacenamiento —el que la decisión anterior evitaba— y
una dependencia de infraestructura más. Se acepta con plazo de retención (§C) y
con la cifra a la vista (§D y [docs/COSTES.md](../COSTES.md)).

**Riesgo.** Un bucket mal configurado expone pliegos. Mitigación: bucket
privado, acceso solo por credencial de servidor, y descarga a usuario siempre
por enlace firmado con caducidad — nunca por URL pública.

**Lo que este ADR no decide.** El proveedor concreto, los formatos soportados
(S8.2) ni la política de OCR (S8.3).
