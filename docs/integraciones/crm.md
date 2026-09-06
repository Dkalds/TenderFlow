---
tags: [integraciones, crm, export]
---

# Exportar el pipeline al CRM

F6.3 del [plan de funcionalidades 2026-09](../plans/2026-09-plan-funcionalidades.md),
con la decisión **D35** cerrada: plantilla genérica de webhook y CSV con este
mapeo documentado. **No hay conector nativo** a Salesforce, Dynamics ni
ninguno otro, y no lo habrá hasta que una organización lo pida por escrito y
diga cuál. Un conector que nadie usa es superficie que hay que mantener y
migrar cada vez que el proveedor cambia su API.

## El mapeo

Un solo mapeo para los dos formatos: el CSV se deriva del mismo payload que
manda el webhook, así que no pueden divergir.

| Campo exportado | De dónde sale | Notas |
|---|---|---|
| `external_id` | `pursuits.licitacion_id` | La clave de deduplicación. **No** el id de la oportunidad: si lo fuera, dos organizaciones que trabajan el mismo expediente crearían dos registros sin relación en un CRM compartido. |
| `account_name` | `licitaciones.organo_contratacion` | La cuenta es **el órgano**, quien compra. No la licitación: en un CRM, una cuenta se repite a lo largo de los años y una oportunidad no. |
| `opportunity_name` | `licitaciones.titulo` | Recortado a 255 caracteres, que es el límite habitual del campo. Sin título, el `id_externo`. |
| `amount` | `licitaciones.importe` | En euros, sin IVA, tal como lo publica la fuente. Vacío si no hay importe publicado — nunca cero. |
| `currency` | Constante `EUR` | |
| `stage` | `pursuits.status`, traducido | Ver la tabla siguiente. |
| `close_date` | `licitaciones.fecha_limite` | La fecha límite de presentación. **No** la fecha prevista de adjudicación (F4.4): esa es una estimación nuestra, y exportarla a un CRM la convertiría en un compromiso que nadie asumió. |
| `owner` | `users.display_name` del responsable | Vacío si la oportunidad no tiene responsable asignado. |
| `source_url` | `licitaciones.url` | El enlace al portal de la fuente. |

### Traducción de etapas

Los ocho estados del workflow no son los de ningún CRM, así que se traducen
aquí y no en el destino: el payload tiene que ser usable sin configurar nada.
Los nombres elegidos son los del embudo estándar, que Salesforce y Dynamics
comparten.

| Estado en TenderFlow | Etapa en el CRM |
|---|---|
| `identified` | Prospecting |
| `qualifying` | Qualification |
| `go_no_go` | Needs Analysis |
| `preparing` | Proposal |
| `submitted` | Negotiation |
| `won` | Closed Won |
| `lost` | Closed Lost |
| `withdrawn` | Closed Lost |

Un estado que no esté en la tabla se exporta como **Prospecting**, no en
crudo. Un CRM con lista de valores cerrada rechazaría el registro entero, y
perder la exportación por una etapa nueva es peor que colocarla en la primera
del embudo, donde alguien la verá y la moverá.

## Lo que NO se exporta, y por qué

Ni el score, ni su explicación, ni las predicciones de baja, ni la ficha del
pliego, ni las etiquetas. Un CRM es un sistema de terceros y esto es una
**exportación**, no una sincronización: cuanto menos salga, menos hay que
explicar el día que alguien pregunte qué se comparte con quién. Si una
organización necesita alguno de esos campos en su CRM, es una conversación —
no un campo más en el payload.

## Idempotencia

El webhook viaja por las plantillas de `webhooks` con la entrega del outbox,
así que un cambio de etapa dispara **un** envío aunque el job reintente. La
deduplicación en el destino la da `external_id`, que es estable durante toda
la vida del expediente.

## Formato CSV

Mismas columnas, mismo orden que la tabla de arriba
(`CABECERAS_CSV` en `services/exports_crm.py`). Cabecera en la primera fila,
UTF-8 con BOM para que Excel no rompa los acentos, y el saneado de fórmulas de
`shared/export_safety.py` — un título que empiece por `=` no puede convertirse
en una fórmula al abrirlo.
