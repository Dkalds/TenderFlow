---
rfc: 2026-09-18-explain-fuera-del-proceso-api
title: Sacar la inferencia de scikit-learn del proceso HTTP — destino de /explain y de /analytics/clusters
issue: (sin issue: backlog P2 «Separar los requirements de la API de los del pipeline/ML» y plan de salida al mercado §4 «Aligerar la imagen de la API»)
author: agent:claude-code
date: 2026-09-18
status: review
---

## Contexto

Desde el 2026-09-18 `docker/Dockerfile.api` instala `requirements-api.txt`, que
no trae scikit-learn, scipy, joblib, statsmodels, networkx ni lxml (C3.1). El
corte se hizo midiendo el cono de imports **incluidos los diferidos** desde
`api.app`, y lo prueba `tests/test_unit_api_imagen_slim.py`: la API arranca en
un proceso que solo puede importar lo que fija su lockfile.

Ningún módulo de la API importa esos paquetes al arrancar. Cinco caminos de
request sí lo hacían en diferido, y este es su estado con la imagen reducida:

| Camino | Qué usaba | Sin el paquete | Cómo se ve |
|---|---|---|---|
| `GET /licitaciones/{id}/explain` | `SAPClassifier` (pipeline sklearn serializado con joblib) | **503** | `detail`: «La explicación del clasificador no está disponible en este despliegue.» |
| `GET /analytics/clusters` | KMeans + TF-IDF en request | **503** | `detail` equivalente; la vista del frontend es `experimental` y pinta el error |
| `GET /feedback/queue?strategy=uncertainty` | `SAPClassifier.predict_proba` | cae a muestreo aleatorio | la respuesta dice `strategy: "random"` |
| `GET /analytics/forecast/*` | Holt-Winters (statsmodels) | regresión lineal | cada fila lleva `modelo: "regresion-lineal"` |
| `GET /competitive/partners` | Louvain (networkx) | sin comunidades | los nodos salen con `community: null` |

Los tres últimos ya degradaban así antes del corte; lo nuevo es que ahora
degradan en producción. Los dos primeros son los que este RFC tiene que
resolver, porque un 503 permanente es una ruta publicada que no funciona.

Un sexto camino apareció al medir y **ya está arreglado**: `GET
/publico/cobertura` importaba `scraper.connectors`, cuyo `__init__` cargaba los
conectores RSS/ATOM y con ellos `lxml`. En la imagen reducida respondía 500. El
paquete re-exporta ahora los conectores en diferido (PEP 562).

### Hechos medidos (2026-09-18)

- **`/explain` no tiene consumidor en el frontend.** En `web/src`, fuera de
  `generated/api.d.ts`, no hay una sola llamada. Sus consumidores posibles son
  clientes con API key; no hay forma de saber desde el repositorio si existen.
- **La vista de clusters es `experimental`** (`web/src/lib/space-views.ts`) y
  cuelga de la flag `mercado_clusters`.
- **El pipeline ya precalcula clusters.** `scheduler/aggregates_precompute.py`
  escribe `mat_clusters` en cada pasada (KMeans sobre TF-IDF de los últimos 12
  meses). La ruta de la API no lo lee: recalcula en request sobre
  `clustering_universe`.
- **El artefacto de `/explain` es el mismo que el pipeline ya carga** para
  clasificar en la ingesta (`scraper/ml_classifier.py`), y
  `SAPClassifier.explain` es la contribución lineal de los términos: coste por
  licitación del orden de un `transform` + un producto escalar.

## Propuesta

### 1. `/explain`: precalcular en el pipeline y servir desde la BD

La explicación depende solo del texto de la licitación y de la versión del
modelo. Ambas cambian en momentos que el pipeline ya conoce: cuando ingiere o
actualiza una licitación, y cuando se activa una versión nueva.

- Tabla `explicaciones_clasificador (licitacion_id, model_version, top_features
  jsonb, prediction, confidence, computed_at)`, PK `(licitacion_id,
  model_version)`.
- El paso de clasificación de la ingesta escribe la fila con `top_k = 20` (el
  máximo que admite la ruta); la ruta recorta a `top_k`.
- Al activar una versión (`POST /models/{name}/activate/{version}`), un job de
  la cola (ADR-028) rellena las del corpus abierto. Mientras no termine, la
  ruta sirve la versión anterior **diciéndolo** en `warning`, que es el
  mecanismo que `api/model_cache.py` ya usa para la degradación.
- La ruta deja de cargar el modelo: `api/model_cache.py` se queda sin
  consumidores en el proceso HTTP y puede retirarse junto con
  `API_MODEL_CACHE_TTL_SECONDS`.

**Contrato:** `ExplainResult` no cambia. Una licitación sin fila (anterior al
backfill o fuera del corpus clasificado) devuelve `explanation: null` con
`warning`, que es exactamente la forma que ya tiene para «Texto vacío».

### 2. `/analytics/clusters`: servir `mat_clusters`

La tabla ya existe y se refresca a diario. La diferencia con el cálculo en
request es que los filtros (`fecha_*`, `ccaa`) se aplicarían sobre una
partición global en vez de reparticionar el subconjunto, y que `n_clusters` y
`auto_k` dejarían de tener efecto. Eso **sí** cambia el contrato de la ruta y
exige su propia decisión: o se retiran esos dos parámetros con el
procedimiento de `docs/api-design.md` (etiqueta `api-breaking`, RFC enlazada,
período de retirada), o se precalculan varias particiones.

Dado que la vista es experimental, la alternativa honesta es **retirar la
ruta** con el mismo procedimiento que
`2026-09-06-rfc-retirada-endpoints-analitica.md`, y reabrirla cuando haya
demanda medida.

### 3. `/feedback/queue`: encolar, no calcular

La cola de active learning ordena 500 candidatas por incertidumbre. Con la
tabla de §1, que guarda `confidence` por licitación y versión, la ruta puede
ordenar por `abs(confidence - 0.5)` en SQL sin cargar el modelo. Hasta entonces, la
degradación a `random` es visible en la respuesta y no requiere acción.

## Alternativas descartadas

- **Volver a meter scikit-learn en la imagen de la API.** Es la vuelta atrás,
  no una alternativa: existe y no toca código (`--build-arg
  REQUIREMENTS_FILE=requirements-pipeline.txt`; en Render, la variable de
  entorno del mismo nombre en `tenderflow-api`). Se usa si este RFC no se
  resuelve antes de que la ausencia de `/explain` importe.
- **Mover `/explain` al worker como petición síncrona.** El worker no expone
  la API (solo `/health`), y hacerle servir peticiones de usuario reabre el
  problema de superficie que ADR-028 cerró.
- **Un segundo servicio "ML API".** Un deployable más para una ruta sin
  consumidor medido.

## Decisión que falta (humana)

1. ¿Se implementa §1 (precalcular `/explain`), o se retira la ruta?
2. ¿`/analytics/clusters` se retira o pasa a leer `mat_clusters` con cambio de
   contrato?
3. Mientras tanto, ¿se despliega la imagen reducida con esas dos rutas en 503,
   o `tenderflow-api` se construye con la variante del pipeline hasta que 1 y
   2 estén hechas?

## Verificación

- `tests/test_unit_api_imagen_slim.py`: la API arranca solo con su lockfile;
  los cinco caminos degradan como dice la tabla.
- `.github/workflows/ci.yml::docker-build`: construye las dos variantes,
  comprueba que la de la API no contiene los paquetes del pipeline y publica el
  tamaño de ambas en el resumen del job.
