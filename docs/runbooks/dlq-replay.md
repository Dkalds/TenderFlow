# Runbook: DLQ Replay

**Propósito**: Reintentar o cerrar las extracciones fallidas de la Dead Letter
Queue (`failed_extractions`).

**Responsable**: Equipo de Operaciones  
**Trigger**: Alerta `DLQ: …` (ver abajo) o degradación del pipeline.

---

## Ver estado actual de la DLQ

La consola de administración (tarjeta «Gestión de DLQ», `GET /admin/dlq`)
enseña las entradas abiertas y agotadas con su resumen. Desde un shell:

```bash
python - <<'EOF'
from db.dlq import count_unresolved, unresolved_error_summary
print(f"Abiertas: {count_unresolved()}")
for r in unresolved_error_summary():
    print(f"  {r['error_type']:30s} n={r['n']:4d}  abiertas={r['abiertas']}  agotadas={r['agotadas']}")
EOF
```

## Cómo se reintenta

`scheduler.dlq_retry.retry_failed_extractions` corre como paso post-ingesta
de cada carril (el diario excluye los meses `bulk_YYYYMM` y
`placsp_watched_company_awards_bulk_YYYYMM`) y como job del scheduler. Para
lanzarlo a mano:

```bash
python -c "from scheduler.dlq_retry import retry_failed_extractions as r; print(r())"
```

Agrupa las entradas vencidas por conector y hace **una** pasada por fuente; el
resultado de esa pasada vale para todas sus entradas. Una entrada sale del
ciclo así:

- **Resuelta**: la pasada fue bien y no volvió a registrar ese mismo fallo.
- **Agotada tras `DLQ_MAX_RETRIES`** (alerta ERROR «entrada agotada sin
  resolver»): la pasada siguió fallando.
- **Agotada en el primer ciclo, con su causa** (alerta WARN):
  - «fuente que no se puede reintentar»: la fuente no tiene dispatch o está
    apagada (sindicación sin URL).
  - «avisos que el reintento no vuelve a leer»: ver la sección siguiente.
  - «avisos que vuelven a fallar al releerlos»: el reproceso del mes volvió a
    registrar el mismo fallo de parseo o persistencia.

Para devolver a la cola o cerrar una entrada concreta, usá «Reintentar» y
«Descartar» en la consola (`POST /admin/dlq/{id}/reintentar|descartar`): dejan
rastro en `audit_log`.

## Avisos que no parsearon o no persistieron (`scope="parse"` / `"adjudicacion"`)

`run_connector` registra un aviso que no parsea con `scope="parse"`, y el upsert
enruta una adjudicación que viola un constraint (CHECK de fecha, FK a
`licitaciones`, NOT NULL) con `scope="adjudicacion"` (RFC
dlq-violaciones-integridad-upsert). En ambos casos `payload_ref` localiza el
aviso; para adjudicaciones, `licitacion_id:nif:importe_adjudicado`.

Su reintento depende de la fuente:

- **Fuentes incrementales** (ATOM, sindicaciones, TED, PSCP, RSS): leen hacia
  delante desde su cursor, que ya dejó atrás el aviso. Reintentarlas no lo
  relee, así que la entrada **se agota en su primer ciclo** con la alerta
  «avisos que el reintento no vuelve a leer». Reencolarla desde la consola la
  vuelve a agotar.
- **Meses** (`bulk_YYYYMM`, `placsp_watched_company_awards_bulk_YYYYMM`): el
  reproceso relee el mes entero. Si el aviso entra, la entrada se resuelve; si
  vuelve a fallar, se agota con «avisos que vuelven a fallar al releerlos».

Inspeccionarlas (abiertas y agotadas):

```bash
python - <<'EOF'
from db.dlq import get_failure, list_exhausted, list_unresolved
for f in list_unresolved(limit=200) + list_exhausted(limit=200):
    if f["scope"] in ("parse", "adjudicacion"):
        r = get_failure(f["id"]) or {}
        print(f"  {f['id']:5d} {f['fuente']:20s} {str(r.get('payload_ref')):40s} {f['error_type']}")
EOF
```

Causa raíz típica de `adjudicacion`: fechas no-ISO (`DD/MM/YYYY`) que violan el
CHECK. Tras corregir la causa, el remedio es reprocesar el mes del aviso (el
`DELETE`-then-insert del upsert y el `UNIQUE` lo hacen idempotente). Cuando la
fila entra limpia, descartá la entrada desde la consola o, para un lote:

```bash
python - <<'EOF'
from db.dlq import mark_matching_resolved
n = mark_matching_resolved("placsp", scope="adjudicacion")
print(f"Marcados como resueltos: {n}")
EOF
```

No hay replay filtrado por tipo de error: `scheduler.dlq_actions` (que citaba
aquí un `retry_by_error_type` que nunca existió) se retiró el 2026-09-28.
