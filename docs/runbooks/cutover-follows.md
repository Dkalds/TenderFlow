---
tags: [runbook, operacion, migracion]
---

# Runbook — mover las lecturas de «Seguir» a `follows`

**Qué hace este runbook:** cierra la migración de [ADR-031](../adr/ADR-031-seguimiento-unificado.md),
que unifica favoritos, empresas vigiladas y descartes del radar en una sola
tabla. La parte aditiva está hecha desde v130; lo que queda es **mover las
lecturas** y, después, retirar los nueve endpoints antiguos.

**Quién lo ejecuta:** una persona. Ningún agente puede cerrar esto solo: el
paso 1 es una decisión de riesgo sobre el dato de clientes reales y el paso 3
exige una RFC con fecha.

**Estado al escribir esto (2026-09-15):** no ejecutado. La escritura doble
lleva funcionando desde v130 y la paridad se mide **sola** en cada pasada
(paso `follows_paridad`). Lo que falta es el criterio de parada y la decisión.

---

## Por qué no se ha hecho ya

ADR-031 §B fija el orden y el motivo: *«retirar antes de la paridad convierte
un bug de backfill en pérdida de datos del usuario»*. Cada fila que esté en
`watchlist_items`, `watchlist_empresas` o `radar_dismissals` y **no** esté en
`follows` es un seguimiento que desaparece de la pantalla el día que la lectura
cambie de sitio. No da error, no sale en ningún log: simplemente ya no está.

Por eso la condición no es «el backfill corrió» sino «cero diferencias medidas
contra producción», y por eso el número se mide a diario en vez de cuando
alguien se acuerda.

## 0. Leer el número (30 segundos)

Ya está medido. El paso `follows_paridad` de la pipeline lo escribe una vez al
día en `ops_events`:

```sql
SELECT ts::date AS dia, value AS faltan, detail
FROM ops_events
WHERE event_type = 'follows_paridad_faltan'
ORDER BY ts DESC
LIMIT 30;
```

| Qué ves | Qué significa |
|---|---|
| `faltan = 0` en los últimos 30 días | La condición de ADR-031 §B se cumple. Seguí al paso 1. |
| `faltan > 0` | **Parar.** Ir a «Si faltan filas». |
| Sin filas | El paso no ha corrido: mirá `pipeline_post_ingestion` en el log de la pasada. |

`detail` desglosa por tabla de origen, que es lo que dice si el hueco es de
favoritos, de empresas o de descartes.

Para ver **qué** filas faltan (con `user_key` y `target_id`, que el evento no
guarda a propósito), hay que correr la herramienta a mano contra la base:

```
python scripts/check_follows_paridad.py --detalle 20
```

### Si faltan filas

El backfill de v130 es idempotente: reejecutarlo es seguro y es lo primero que
hay que probar. Si tras reejecutarlo siguen faltando, **no es el backfill**:
es la escritura doble, y hay un camino de alta que no pasa por ella. Buscar en
`db/repositories/watchlist.py`, `db/watchlist_empresas.py` y
`db/radar_dismissals.py` — los tres tienen la escritura doble al lado del alta;
lo que falta será un cuarto sitio que escribe en esas tablas sin pasar por su
repositorio.

**Las filas que sobran no bloquean.** Son casi siempre borrados anteriores a la
escritura doble que nadie propagó. Se revisan, pero no impiden migrar: lo peor
que hacen es que el usuario vea reaparecer algo que quitó hace meses.

## 1. Mover las lecturas (cambio de código, con PR)

Tres controles siguen leyendo de su tabla:

| Control | Dónde |
|---|---|
| Estrella del expediente | `web/src/app/(dashboard)/detalle/_hooks/use-detalle-favoritos.ts` |
| Botón de empresa vigilada | `web/src/hooks/use-empresas-watchlist.ts` |
| Descarte del radar | `web/src/app/(dashboard)/radar/_hooks/use-radar-consola.ts` |

El componente destino ya existe y está en producción en el panel de órgano:
`web/src/components/seguir-boton.tsx`, sobre `web/src/hooks/use-follows.ts`.
ADR-031 §C es explícito sobre por qué se unifican: *«un control que se comporta
distinto en dos pantallas es dos controles»*.

Mover uno por PR, no los tres a la vez. Si algo se rompe, lo que hay que poder
decir es cuál.

## 2. Ventana de observación

Con las lecturas movidas, la escritura doble **sigue puesta**: las tablas
antiguas siguen recibiendo, así que la vuelta atrás es revertir el PR y nada
más. Dejarla al menos un ciclo de facturación antes del paso 3.

El paso `follows_paridad` sigue corriendo y ahora mide la dirección contraria
de lo mismo: si aparecen diferencias **después** de mover la lectura, es que la
escritura doble se rompió y los usuarios están viendo una foto vieja.

## 3. Retirar los endpoints antiguos (RFC)

ADR-031 §B punto 3 y la política de deprecación de
[api-design.md](../api-design.md): ventana de 90 días, cabeceras `Deprecation`
y `Sunset`, y RFC con fecha. Son nueve endpoints; el ADR deja la fecha
explícitamente sin decidir.

Sólo después de esto se puede quitar la escritura doble y, con ella, las tres
tablas de origen.

---

## Qué NO hace el paso automático

`scheduler/jobs/follows_paridad.py` **mide y nada más**. No reescribe
`follows`, no repara huecos y no mueve ninguna lectura, y hay un test que lo
fija (`tests/test_follows_paridad_job.py`). La tentación de «ya que lo he
detectado, lo arreglo» convertiría el número en una tautología —siempre cero,
porque el propio medidor lo pone a cero— y ADR-031 se quedaría sin la señal que
pide.
