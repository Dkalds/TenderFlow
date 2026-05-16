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

## Purgar mensajes irrecuperables (> 7 días)

```bash
python - <<'EOF'
from db.dlq import purge_old_entries
n = purge_old_entries(older_than_days=7)
print(f"Purgados: {n} mensajes")
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
