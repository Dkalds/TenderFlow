# Runbook: Rate Limit Reset

**Propósito**: Resetear límites de tasa de un cliente bloqueado (login o API).

**Responsable**: Equipo de Operaciones  
**Trigger**: Alerta `rate_limit_blocked` o reporte de usuario bloqueado.

---

## Ver clientes con rate limit activo

```bash
python - <<'EOF'
import time
from db.database import connect

now = time.time()
window = 300.0  # 5 minutos (ventana de login)

with connect() as c:
    rows = c.execute(
        "SELECT key, COUNT(*) as hits, MIN(ts) as oldest, MAX(ts) as newest "
        "FROM rate_limits "
        "WHERE ts >= ? "
        "GROUP BY key "
        "ORDER BY hits DESC",
        (now - window,),
    ).fetchall()
    if not rows:
        print("Ningún cliente con rate limit activo.")
    for r in rows:
        print(f"  key={r[0]}  hits={r[1]}  oldest={r[2]:.0f}  newest={r[3]:.0f}")
EOF
```

## Resetear rate limit de un cliente específico

```bash
python - <<'EOF'
import sys
key = sys.argv[1] if len(sys.argv) > 1 else input("Rate limit key (e.g. login_fail:<hash>): ")
from db.database import connect
with connect() as c:
    c.execute("DELETE FROM rate_limits WHERE key = ?", (key,))
print(f"Rate limit reseteado para: {key}")
EOF
```

## Resetear todos los rate limits

> ⚠️ Usar con precaución — puede permitir ataques en curso.

```bash
python - <<'EOF'
from db.database import connect
with connect() as c:
    c.execute("DELETE FROM rate_limits")
print("Todos los registros de rate_limits eliminados.")
EOF
```

## Ajustar límites en configuración

Variables de entorno (o `.env`):

```bash
# API rate limiting (api/app.py)
# API_RATE_LIMIT_MAX_CALLS=120       (default: 120 llamadas)
# API_RATE_LIMIT_WINDOW_SECONDS=60   (default: ventana de 60s)
```

Reinicia la API tras el cambio:

```bash
docker compose restart api
```
