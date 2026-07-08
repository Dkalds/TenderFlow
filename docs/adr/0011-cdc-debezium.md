---
id: ADR-0011
title: "CDC con Debezium — Decisión y Alternativas"
status: proposed
date: 2026-05-16
deciders: "Equipo de Plataforma"
related:
  - "[[ADR-004-sqlite-turso-vs-postgres]]"
tags: [adr]
---

# ADR-0011: CDC con Debezium — Decisión y Alternativas

**Estado**: Registrado — NO implementado por defecto  
**Fecha**: 2026-05-16  
**Autores**: Equipo de Plataforma  
**Relacionados**: [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] (SQLite/Turso), K2 (event sourcing)

---

## Contexto

El sistema actual persiste licitaciones en SQLite (local) con sincronización a Turso
(libSQL). Los cambios en las tablas `licitaciones` y `licitaciones_history` son la
principal fuente de eventos para otros sistemas (notificaciones, modelos ML, analytics).

Se evaluó **Change Data Capture (CDC)** con Debezium para:
1. Propagar cambios a Kafka en tiempo real sin modificar la aplicación.
2. Habilitar event streaming a microservicios downstream.
3. Reducir el acoplamiento entre el scraper y el dashboard/API.

---

## Decisión

**Se decide NO implementar Debezium/CDC como capa primaria** en el estado actual del
proyecto. En su lugar, se usa el event store propio (`db/events.py`, tabla
`domain_events`) que cubre los mismos casos de uso con menor overhead operativo.

---

## Razones para NO adoptar Debezium ahora

| Factor | Detalle |
|---|---|
| **SQLite no soportado nativamente** | Debezium soporta MySQL, Postgres, SQL Server, MongoDB y Oracle. Para SQLite existe un conector experimental no oficial (`debezium-connector-sqlite`) con fiabilidad no probada en producción. |
| **Complejidad operativa** | Requiere Kafka + Zookeeper + Debezium Connect + esquemas Avro/Protobuf. El stack actual es un solo proceso Python + SQLite. |
| **Alternativa implementada** | `db/events.py` proporciona event sourcing ligero con append-only log en `domain_events`. Cubre: watchlist, feedback, y puede extenderse a cualquier agregado. |
| **Migración gradual posible** | Si en el futuro se migra a Postgres (ver [[ADR-004-sqlite-turso-vs-postgres|ADR-004]]), Debezium puede añadirse incrementalmente apuntando al conector `debezium-connector-postgresql`. |

---

## Cuándo reconsiderar Debezium

- Si el sistema migra a PostgreSQL o MySQL.
- Si aparecen >3 sistemas downstream que necesiten cambios en tiempo real.
- Si el equipo crece y puede asumir la carga operativa de Kafka.

---

## Arquitectura de referencia (futura, no implementada)

```
SQLite/Postgres ──► Debezium Connector ──► Kafka Topic: licitaciones.changes
                                                    │
                                     ┌──────────────┼──────────────┐
                                     ▼              ▼              ▼
                              Notificaciones    Reentrenamiento   Analytics
                              (dashboard)         ML modelo        (BI)
```

---

## Conector de referencia (ejemplo para PostgreSQL)

Si en el futuro se decide implementar, el conector Debezium para PostgreSQL
se configuraría así:

```json
{
  "name": "licitaciones-pg-connector",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "postgres",
    "database.port": "5432",
    "database.user": "debezium",
    "database.password": "${file:/secrets.properties:db.password}",
    "database.dbname": "licitaciones",
    "database.server.name": "licitaciones",
    "table.include.list": "public.licitaciones,public.licitaciones_history",
    "plugin.name": "pgoutput",
    "slot.name": "debezium_slot",
    "publication.name": "debezium_pub",
    "transforms": "unwrap",
    "transforms.unwrap.type": "io.debezium.transforms.ExtractNewRecordState",
    "transforms.unwrap.drop.tombstones": "false",
    "key.converter": "org.apache.kafka.connect.json.JsonConverter",
    "value.converter": "org.apache.kafka.connect.json.JsonConverter",
    "topic.prefix": "licitaciones"
  }
}
```

Para registrar el conector en Debezium Connect:

```bash
curl -X POST http://localhost:8083/connectors \
  -H "Content-Type: application/json" \
  -d @docs/debezium-connector.json
```

---

## Alternativa actual recomendada

Usar `db/events.py`:

```python
from db.events import append_event

# Al insertar/actualizar una licitación
append_event(
    "licitacion.updated",
    lic.id_externo,
    "licitacion",
    {"titulo": lic.titulo, "importe": lic.importe, "estado": lic.estado},
    actor_id="scraper",
)

# Para replay / audit
from db.events import get_events
history = get_events("licitacion", "PRO/2024/12345")
```

---

## Referencias

- [Debezium SQLite connector (experimental)](https://github.com/memiiso/debezium-server-jdbc)
- [Debezium PostgreSQL connector docs](https://debezium.io/documentation/reference/stable/connectors/postgresql.html)
- [[ADR-004-sqlite-turso-vs-postgres|ADR-004]]: SQLite/Turso vs. Postgres
- `db/events.py` — implementación actual de event sourcing
