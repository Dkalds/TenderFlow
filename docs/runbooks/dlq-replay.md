# Runbook: DLQ Replay

**Propósito**: Reintentar mensajes fallidos de la Dead Letter Queue (DLQ).

**Responsable**: Equipo de Operaciones  
**Trigger**: Alerta `dlq_size_critical` o degradación del pipeline.

---

## Ver estado actual de la DLQ

```bash
python - <<'EOF'
from db.database import connect
with connect() as c:
    rows = c.execute(
        "SELECT error_type, COUNT(*) as n, MAX(created_at) as last "
        "FROM dlq GROUP BY error_type ORDER BY n DESC"
    ).fetchall()
    for r in rows:
        print(f"  {r[0]:30s} n={r[1]:4d}  last={r[2]}")
EOF
```

## Replay de todos los mensajes en DLQ

```bash
python -m scheduler.dlq_retry
```

## Replay filtrado por tipo de error

```bash
python - <<'EOF'
from scheduler.dlq_actions import retry_by_error_type
retry_by_error_type("parse_error", max_items=50)
EOF
```

## Violaciones de integridad de adjudicaciones (`scope="adjudicacion"`)

Una adjudicación que viola un constraint del schema (CHECK de fecha, FK a
`licitaciones`, NOT NULL) ya no se descarta en silencio: el upsert la enruta a la
DLQ con `scope="adjudicacion"` (RFC dlq-violaciones-integridad-upsert), de modo que
es **replayable** en vez de perderse. El `payload_ref` localiza la fila exacta con
el formato `licitacion_id:nif:importe_adjudicado`.

Inspeccionar las violaciones de integridad pendientes:

```bash
python - <<'EOF'
from db.dlq import list_unresolved
for f in list_unresolved():
    if f["scope"] == "adjudicacion":
        print(f"  {f['payload_ref']:40s} {f['error_type']}  intentos={f['retry_count']}")
EOF
```

Causa raíz típica: fechas no-ISO (`DD/MM/YYYY`) que violan el CHECK GLOB. Una vez
corregida la causa (p. ej. tras aterrizar la normalización canónica de fechas), el
replay reinserta la adjudicación de forma **idempotente** (DELETE-then-insert +
`UNIQUE`), sin duplicar.

## Purgar mensajes irrecuperables (> 7 días)

```bash
python - <<'EOF'
from db.dlq import purge_old_entries
n = purge_old_entries(older_than_days=7)
print(f"Purgados: {n} mensajes")
EOF
```

## Replay específico: `scope="adjudicacion"`

Tras el RFC `dlq-violaciones-integridad-upsert`, las violaciones de constraint
(CHECK/FK/NOT NULL) en `replace_adjudicaciones[_batch]` se persisten en
`failed_extractions` con `scope="adjudicacion"` y
`payload_ref="{licitacion_id}:{nif}:{importe_adjudicado}"`. Para inspeccionarlas:

```bash
python - <<'EOF'
from db.dlq import list_unresolved
for r in list_unresolved(limit=50):
    if r["scope"] == "adjudicacion":
        print(f"  {r['id']:5d} {r['payload_ref']:40s} retry={r['retry_count']}  {r['error_message'][:80]}")
EOF
```

Tras corregir la causa raíz (típicamente: re-ingestar tras un fix de
normalización en el parser), el replay se hace re-ingestando el XML de origen:
el `DELETE`-then-insert del upsert garantiza idempotencia y el `UNIQUE` evita
duplicados. Cuando la fila vuelve a entrar limpia, marca el registro como
resuelto:

```bash
python - <<'EOF'
from db.dlq import mark_matching_resolved
n = mark_matching_resolved("placsp", scope="adjudicacion")
print(f"Marcados como resueltos: {n}")
EOF
```

## Verificar después del replay

```bash
python - <<'EOF'
from db.database import connect
with connect() as c:
    n = c.execute("SELECT COUNT(*) FROM dlq WHERE status='pending'").fetchone()[0]
    print(f"Mensajes pendientes en DLQ: {n}")
EOF
```
