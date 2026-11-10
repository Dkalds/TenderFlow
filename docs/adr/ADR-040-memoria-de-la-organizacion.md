---
id: ADR-040
title: "Memoria de la organización: el texto de sus adjuntos se indexa en un almacén propio y solo se cita literal"
status: accepted
date: 2026-11-10
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-029-almacen-de-objetos]]"
  - "[[ADR-034-rls-por-tenant]]"
  - "[[ADR-028-cola-de-trabajo-y-worker]]"
  - "[[ADR-030-identidad-user-id-y-oidc]]"
tags: [adr]
---

# ADR-040 — Memoria de la organización: almacén propio y citas literales

- **Estado:** aceptado
- **Fecha:** 2026-11-10
- **Acota:** [ADR-034](ADR-034-rls-por-tenant.md) §C, solo para la tabla
  `pursuit_attachment_chunks`: su política no tiene paso franco sin ámbito.
- **Relacionado:** [ADR-029](ADR-029-almacen-de-objetos.md) (de dónde sale el
  binario), [ADR-028](ADR-028-cola-de-trabajo-y-worker.md) (quién indexa),
  [ADR-030](ADR-030-identidad-user-id-y-oidc.md) §D (el adjunto es dato
  corporativo).
- **Implementa:** migración `v179_memoria_organizacion`, CU-37 de
  [docs/casos-de-uso.md](../casos-de-uso.md).

---

## Contexto

Una organización guarda en cada oportunidad la propuesta que presentó
(`pursuit_attachments`, C6.3). Desde `v127` cada adjunto tiene una columna
`indexable`, que nació en `false` y que ningún código leía: el RAG trabajaba
solo sobre el corpus público de pliegos (`documentos`, `documento_pages`,
`documento_chunks`), y nada en `services/rag/` filtra por organización porque
todo lo que hay ahí es público.

Lo que se pide es que el equipo pueda apoyarse en lo que ya escribió —«¿qué
metodología de migración seguimos la última vez?»— sin que esa propuesta, que
es el dato más sensible que guarda el producto, pueda llegar jamás a otra
organización.

## Decisión

### A. El texto indexado vive en una tabla propia, no en el corpus de pliegos

`pursuit_attachment_chunks` (v179) guarda los fragmentos de un adjunto con su
página y su embedding. No se reutilizan `documentos` ni `documento_chunks` con
una columna `organization_id`: esas tablas las leen sin organización la
búsqueda, la ficha, la señal tecnológica, el MCP interno y los jobs nocturnos,
y cada una de esas consultas habría tenido que acertar el filtro. Con una
tabla aparte, ninguna consulta que ya existe puede devolver una propuesta.

No hay tabla de páginas: el fragmento lleva su `page_number` y nadie lee el
texto privado página a página. Es una copia menos.

### B. Tres capas de aislamiento, y la política no tiene paso franco

1. **El SQL.** Toda consulta de `db/repositories/pursuit_attachments.py` exige
   la organización en el fragmento **y** en el adjunto, y que el adjunto siga
   vivo y con el permiso puesto. No hay filtro posterior en Python.
2. **La forma de la fila.** La clave ajena es compuesta —`(attachment_id,
   organization_id)` contra `pursuit_attachments (id, organization_id)`—: un
   fragmento no puede declarar una organización distinta de la de su adjunto.
3. **RLS estricta.** Las políticas `tenant_scope_`/`tenant_guard_` de la tabla
   comparan `organization_id` con `app.organization_id` **sin** el primer
   término de ADR-034 §C. Sin ámbito fijado no se ve ni se escribe nada. En el
   resto de tablas corporativas el paso franco existe para que scheduler,
   scripts y migraciones sigan funcionando; aquí ningún proceso sin ámbito
   tiene motivo para leer una propuesta, y el que indexa lo fija con
   `tenant_scope`. Los borrados en cascada no dependen de la política.

El MCP interno no recibe permiso sobre la tabla (`mcp_server/catalogo.py` la
declara oculta).

### C. El texto propio no entra en ningún prompt: se cita literal

El Investigador y el guion de la oferta enseñan **extractos literales** de los
documentos indexados, al lado de la respuesta o del criterio, rotulados como
de la organización y con su fichero, su página y su oportunidad de origen. No
se le pasan al modelo para que los resuma ni para que redacte con ellos. Es la
regla de D33 —esquema con citas, nunca prosa generada— y tiene dos efectos
más: el texto de una propuesta no sale hacia el proveedor del LLM, y no puede
acabar en la caché de respuestas ni en la del guion, que son compartidas entre
organizaciones. Las citas se buscan en cada petición y no se guardan. Si esa
búsqueda falla, la respuesta y el guion salen igual y lo dicen: que no haya
citas propias no se presenta como que no las hubiera.

### D. El permiso es por fichero, se retira borrando y deja rastro

Quien puede subir adjuntos puede marcar uno como indexable y desmarcarlo.
Desmarcarlo, o retirar el adjunto, borra sus fragmentos y sus embeddings **en
la misma transacción** que el permiso: no hay instante en que el permiso esté
retirado y el texto siga ahí. El indexado bloquea la fila del adjunto antes de
escribir, así que un job que llegue tarde no deja nada. Cada cambio queda en
el rastro de la organización (`pursuit_attachment.indexing_changed`), y esa
fila se escribe también en la transacción del permiso
([ADR-039](ADR-039-auditoria-como-condicion-del-control-de-acceso.md) §3): si
el rastro no se puede escribir, el permiso no cambia.

Las citas las recibe quien podría abrir el adjunto: cualquier sesión de la
organización, y una clave de API solo si tiene `pursuits:read`. Vale igual
para el Investigador y para el guion (`api/scopes.py`).

### E. Indexa la cola; los vectores pueden llegar después

El indexado es un job (`indexado_adjunto`): extrae con el mismo código que los
pliegos, fragmenta y guarda. Es idempotente y reintentable. Donde el proceso
no tiene motor para embeber un documento entero —la API en producción, que
solo lleva el motor de consulta— el documento se guarda sin vectores y ya es
citable por palabras; el job nocturno de embeddings los rellena. La búsqueda
vectorial es exacta y acotada a la organización: un índice aproximado global
filtraría después de elegir vecinos entre todas.

### F. El coste tiene tope, y el tope es configuración

Cuántos documentos puede tener indexados una organización y de qué tamaño
(`MEMORIA_ORG_MAX_DOCUMENTOS`, `MEMORIA_ORG_MAX_BYTES_POR_DOCUMENTO`) sale del
entorno, con un suelo conservador por defecto; `0` apaga el indexado y la
recuperación. Qué se ofrece a cada organización es una decisión de producto
que este ADR no toma.

## Consecuencias

**A favor.** El aislamiento no depende de acertar un filtro en consultas que
ya existían. Lo que se enseña se puede comprobar abriendo el fichero. Retirar
el permiso es un borrado, no una marca.

**En contra.** Hay dos caminos de fragmentos (pliegos y adjuntos) que comparten
extractor y chunker pero no tabla. El modelo no «usa» los documentos propios
para responder: quien quiera esa función tendrá que revisar §C a conciencia,
con el encargado del tratamiento del LLM y la caché por delante.

**Riesgo.** La RLS es un respaldo: mientras el runtime conecte con un rol que
la salta (ADR-034, «Producción hoy»), la frontera efectiva es el SQL. Por eso
el escenario de CU-37 prueba el aislamiento por la API, y los tests con rol
sonda prueban la política aparte.

**Lo que este ADR no decide.** La cuota por organización, el coste de los
embeddings, ni si las citas propias deben salir en el PDF del guion.
