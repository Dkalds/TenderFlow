---
tags: [runbook, operacion, migracion]
---

# Runbook — fechas a `timestamptz`, fase 1 (sombras `*_ts`)

**Qué hace este runbook:** lleva a producción las sombras `<columna>_ts
timestamptz` de `v159_fechas_ts_sombra` y el índice de `v160_fechas_ts_indices`
(ítem «Pasar las fechas de `text` a `timestamptz`» del
[backlog](../IMPROVEMENT_BACKLOG.md)) sin reescribir ninguna tabla ni tomar un
lock exclusivo largo. Es la misma receta que el
[núcleo tipado](nucleo-tipado-ventana.md), extendida a catorce fechas más.

| Tabla | Columnas con sombra | Quién mantiene la sombra |
|---|---|---|
| `licitaciones` | `fecha_extraccion`, `primera_extraccion`, `fecha_inicio`, `fecha_fin`, `fecha_actualizacion_fuente` | escritura dual de `db/upsert.py` (salvo `primera_extraccion`, que no escribe nadie: solo backfill) |
| `adjudicaciones` | `fecha_adjudicacion` | trigger `trg_fechas_ts_adjudicaciones` |
| `licitaciones_history` | `captured_at` | trigger |
| `documentos` | `created_at`, `fetched_at`, `updated_at` | trigger |
| `pursuit_events` | `created_at` | trigger (solo `INSERT`: es append-only) |
| `user_notifications` | `created_at`, `read_at` | trigger |

**Quién lo ejecuta:** una persona con acceso de escritura a producción, por
`migrate.yml` (manual) para las migraciones y desde una máquina con
`DATABASE_URL` de producción para el backfill.

**Estado al escribir esto (2026-10-25):** no ejecutado. Volumen medido con el
MCP de solo lectura ese día: `licitaciones` 88.925 filas vivas,
`adjudicaciones` 80.327, `licitaciones_history` 61.240, `documentos` 56.358,
`user_notifications` 60, `pursuit_events` 54. En las columnas de texto hay
mezcla de formatos (`2026-09-04T…+00:00` y `2026-09-04 …+00` en
`fecha_extraccion` y `primera_extraccion`): exactamente lo que el tipo debe
dejar de permitir. Todas las formas vistas las traduce
`nucleo_iso_a_timestamptz` (`tests/test_unit_fechas_ts.py`).

---

## Orden

1. **Plan:** `alembic upgrade v158_domain_events_pscp_rekey:v159_fechas_ts_sombra --sql`.
   Debe ser: `SET LOCAL lock_timeout`, un `ALTER TABLE … ADD COLUMN IF NOT
   EXISTS … timestamptz` por tabla **sin `DEFAULT` ni `USING`**, cinco
   funciones y triggers `fechas_ts_*`, el relleno de `pursuit_events` (con su
   trigger append-only pausado) y de `user_notifications`, y `RESET
   lock_timeout`. Si aparece un `DEFAULT` o un `ALTER COLUMN`, parar.
2. **Migración:** `alembic upgrade v159_fechas_ts_sombra` (no `head`: `v160` va
   después del backfill). Segundos. Si falla por `lock_timeout`, hay una
   consulta larga sobre alguna de las seis tablas: esperar y reintentar, no
   subir el timeout.
3. **Despliegue** del código de la rama. La escritura dual se enciende sola:
   `db/upsert.py` pregunta al catálogo en cada chunk si existen las sombras de
   `licitaciones` y, si existen, las escribe. Desplegar antes que la migración
   también es seguro (sin columnas, el upsert es el de siempre). Los triggers de
   las demás tablas funcionan desde el paso 2 sin desplegar nada.
4. **Backfill:**

   ```bash
   python -m scripts.backfill_fechas_ts --verificar        # línea base
   python -m scripts.backfill_fechas_ts --lote 5000 --pausa 0.1
   ```

   Recorre `licitaciones`, `adjudicaciones`, `licitaciones_history`,
   `documentos` y `user_notifications` por clave primaria, una transacción por
   lote, `lock_timeout` de 2 s (cede ante la ingesta y reintenta). Cada lote
   imprime su última clave; si se corta: `--tabla <t> --desde <clave>`. Salida
   2 = cinco reintentos agotados: mirar `pg_stat_activity` antes de seguir.

   Duración estimada con el volumen de 2026-10-25: ~260 k filas en total y
   ~650 k llamadas a la función de conversión (que abre una subtransacción por
   su bloque `EXCEPTION`, así que el cuello es CPU): **del orden de minutos**
   (2-10). Medir el primer lote de `licitaciones` y extrapolar. Si la tabla
   llegara a 1,6 M filas, contar 20-40 min solo para ella.
5. **Verificación** (criterio de parada):

   ```bash
   python -m scripts.backfill_fechas_ts --verificar
   ```

   | Contador | Esperado | Si no |
   |---|---|---|
   | divergentes (total y por sombra) | **0** | Repetir el paso 4. Si persiste en `licitaciones`, hay un escritor fuera del upsert tocando esas fechas: encontrarlo. |
   | `<columna>_no_iso` | anotar | Texto presente que no es una fecha: la sombra dice bien que no hay fecha, pero son las filas que la fase 2 perdería. Revisarlas antes de la fase 2. |

6. **Índice:** `alembic upgrade v160_fechas_ts_indices` (`CREATE INDEX
   CONCURRENTLY`, no bloquea escrituras; segundos a un minuto). Comprobar que
   no quedó `INVALID`:

   ```sql
   SELECT c.relname, i.indisvalid FROM pg_index i
   JOIN pg_class c ON c.oid = i.indexrelid
   WHERE c.relname = 'idx_lic_fecha_extraccion_ts';
   ```

   Si sale `false`: `DROP INDEX CONCURRENTLY idx_lic_fecha_extraccion_ts;` y
   repetir.
7. **Lecturas:** `FECHAS_TS_LECTURA=true` en la API, **solo** con el paso 5 en
   cero y el paso 6 válido. Mueve a instante: los cortes y órdenes de
   «desde tu última visita» (`NovedadesRepository`: historial, documentos,
   oportunidades), el orden del historial de una licitación (`get_history`),
   el de las alertas (`db.notifications`) y `MAX(fecha_extraccion_ts)` de
   `/meta/last-extraction`. Lo proyectado sigue siendo el texto: ningún DTO
   cambia. Sin el índice de `v160`, ese `MAX` vuelve a ser un seq scan como el
   que motivó `v77`.

## Vuelta atrás

- Lecturas: `FECHAS_TS_LECTURA=false`, sin despliegue; cada fragmento vuelve a
  la columna de texto byte a byte.
- Índice: `alembic downgrade v159_fechas_ts_sombra`.
- Columnas y triggers: `alembic downgrade v158_domain_events_pscp_rekey`
  (`DROP TRIGGER`, `DROP FUNCTION`, `DROP COLUMN`: solo catálogo). El upsert deja
  de escribir las sombras en su siguiente chunk sin reinicio.

## Fase 2 (no es de esta ventana)

Retirar las columnas de texto, descrita en el ítem del backlog: requiere que
todos los lectores lean ya la sombra y RFC por ser cambio de persistencia.
