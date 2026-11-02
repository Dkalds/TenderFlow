# Runbook: etiquetar a mano la muestra de «¿es TI?»

**Propósito**: producir las etiquetas humanas de las que sale el golden real del
binario `es_ti` (`tests/fixtures/golden_ti.jsonl`), sin depender de que antes se
haya lanzado el LLM sobre la muestra de F2 (D3 del
[plan de tres niveles](../plans/2026-09-27-clasificacion-tres-niveles.md)).

**Responsable**: el propietario o quien él designe (las etiquetas son decisiones
de producto, no de código).
**Coste**: ~400 licitaciones, unas 3–4 h repartibles.

---

## Reglas que no se negocian

- **Se etiqueta leyendo el anuncio** (título, descripción, CPV, órgano, y el
  pliego si hace falta). El fichero no trae la etiqueta de las reglas, la
  probabilidad del modelo ni la propuesta del LLM, a propósito: el golden es lo
  que va a juzgar a esas tres fuentes.
- **Una fila sin etiqueta no es un negativo.** Si no se puede decidir, se deja
  `es_ti: null` y una `nota`; el import la salta.
- **No se fabrican etiquetas** ni se rellenan con reglas o con el LLM, ni se
  edita `golden_ti.jsonl` a mano: sale de `ml_feedback` con
  `scripts/exportar_golden_ti.py`.
- **Sin golden humano no se promociona ningún modelo** (gate de
  [model-rollback.md](model-rollback.md#criterio-de-promoción-cuándo-una-versión-puede-activarse)).

## 1. Generar la muestra

Solo lectura contra la BD (usa `connect_read`); con la misma tabla y la misma
semilla sale la misma muestra:

```bash
ENV=prod PYTHONPATH="$PWD" python scripts/muestra_etiquetado_ti.py generar \
    --salida data/etiquetado/muestra_ti.jsonl
```

Por defecto: 400 licitaciones, semilla `etiquetado-ti-2026-10-23`, años con
estrato propio desde 2023. `data/` no se versiona: el fichero no va al repo.

Estratos: fuente (PLACSP, PSCP, TED, otras) x CPV (48, 72, otros) x si casa
alguna keyword x año de publicación. Cuotas por raíz cuadrada del tamaño
(`services.ml.muestra_estratificada.repartir_cuotas`), con al menos una por
estrato. Quedan fuera los duplicados confirmados.

*Medido en producción el 2026-10-23 por el MCP de solo lectura* (misma consulta,
6 s): 86.797 licitaciones candidatas en 71 estratos → 400 seleccionadas, 400
distintas; 158 PLACSP, 218 PSCP, 22 TED y 2 de otras fuentes; 177 con keyword y
223 sin ella; 199 publicadas en 2025–2026 y el resto antes, así que el holdout
temporal del golden (el 50 % más reciente) queda poblado por los dos lados.

## 2. Etiquetar

Cada línea del JSONL es una licitación. Se rellenan cinco campos:

| Campo | Qué poner |
| --- | --- |
| `es_ti` | `true` o `false`; `null` si no se puede decidir. |
| `tecnologia` | Solo si `es_ti` es `true`: la familia principal, una de `TECH_LABELS` (`config/keywords.py`). |
| `tecnologias_secundarias` | Otras familias que el contrato cubre, misma lista. Vacío si no hay. |
| `nota` | Opcional: por qué, sobre todo en los casos de frontera. Máx. 500 caracteres. |
| `etiquetado_por` | Quién etiqueta (iniciales). Se guarda en la nota. |

**Frontera de «TI»** (D1, aprobada):

- **Dentro**: software (licencias, SaaS, desarrollo, mantenimiento de
  aplicaciones), servicios TI (soporte, CAU, outsourcing, consultoría TI),
  infraestructura (cloud, hosting, CPD, redes de datos, virtualización,
  servidores, almacenamiento, backup), ciberseguridad, datos/BI/IA,
  administración electrónica, sanidad digital, GIS y hardware de puesto.
- **Fuera**: formación sobre herramientas (salvo dentro de una implantación),
  suscripciones a contenidos (revistas, bases de datos bibliográficas o
  clínicas), telefonía de voz, publicidad y eventos, y obra civil o
  climatización del CPD.
- **Contratos menores ya adjudicados** siguen siendo TI: si son oportunidad lo
  dicen el estado y el procedimiento, no este clasificador.
- **Casos que D1 no resuelve** (lotes mixtos, TI como accesorio de otra
  cosa): la decisión es de quien etiqueta, y va en la `nota` para poder
  revisarla luego en bloque. No hay regla escrita para ellos todavía.
- **«Tiene keyword pero no es TI»** (p. ej. «SAP» como siglas de otra cosa,
  «red» de saneamiento): `false`. Son los casos que el golden legado no tenía y
  los que más informan.

## 3. Volcar las etiquetas

Con una API key con scope `feedback:write` (`api/scopes.py`) **de una cuenta
administradora** (con otra, `POST /api/v1/feedback` responde 403):

```bash
TENDERFLOW_API_KEY=... python scripts/muestra_etiquetado_ti.py importar \
    --entrada data/etiquetado/muestra_ti.jsonl \
    --api-url https://tenderflow-jrtr.onrender.com
```

- Valida el fichero entero **antes** de mandar nada: un `es_ti` que no sea
  booleano, una familia desconocida o `es_ti: false` con familia paran el
  volcado sin haber escrito ninguna fila.
- Cada etiqueta entra por `POST /api/v1/feedback` como `source='revision_ti'`,
  igual que el formulario de `/ops?vista=etiquetado`, con su evento de
  auditoría. La cabecera `Idempotency-Key` hace que relanzar el import no
  duplique filas; cambiar una etiqueta y relanzar sí añade la nueva (manda la
  más reciente).

## 4. Regenerar el golden y medir

```bash
ENV=prod PYTHONPATH="$PWD" python scripts/exportar_golden_ti.py
ENV=prod PYTHONPATH="$PWD" python scripts/medir_acuerdo_llm.py   # cuando haya señal LLM
```

El primer export congela el corte temporal del holdout en la cabecera de
`golden_ti.jsonl`; los siguientes reparten contra ese corte. El fichero
regenerado se commitea en un PR propio.
