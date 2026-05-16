# Runbook: Rate Limit Reset

**Propósito**: Resetear límites de tasa de una API Key o IP bloqueada.

**Responsable**: Equipo de Operaciones  
**Trigger**: Alerta `rate_limit_blocked` o reporte de usuario bloqueado.

---

## Ver API Keys con rate limit activo

```bash
python - <<'EOF'
from db.database import connect
from datetime import UTC, datetime
now = datetime.now(UTC).isoformat()
with connect() as c:
    rows = c.execute(
        "SELECT api_key_prefix, requests_count, window_start, blocked_until "
        "FROM rate_limits "
        "WHERE blocked_until > ? "
        "ORDER BY blocked_until DESC",
        (now,),
    ).fetchall()
    if not rows:
        print("Ninguna API Key bloqueada actualmente.")
    for r in rows:
        print(f"  prefix={r[0]}  count={r[1]}  blocked_until={r[3]}")
EOF
```

## Resetear rate limit de una API Key específica

```bash
python - <<'EOF'
import sys
api_key_prefix = sys.argv[1] if len(sys.argv) > 1 else input("API Key prefix: ")
from db.database import connect
with connect() as c:
    c.execute("DELETE FROM rate_limits WHERE api_key_prefix=?", (api_key_prefix,))
print(f"Rate limit reseteado para: {api_key_prefix}")
EOF
```

## Resetear todos los rate limits

> ⚠️ Usar con precaución — puede permitir ataques en curso.

```bash
python - <<'EOF'
from db.database import connect
with connect() as c:
    n = c.execute("DELETE FROM rate_limits").rowcount
print(f"Eliminados {n} registros de rate_limits.")
EOF
```

## Ajustar límites en configuración

Edita `config/settings.py` o variables de entorno:

```bash
# API_RATE_LIMIT_PER_MINUTE=60  (default)
# API_RATE_LIMIT_BURST=10
```

Reinicia la API tras el cambio:

```bash
make restart-api
```
