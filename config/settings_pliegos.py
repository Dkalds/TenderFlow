"""Settings de pliegos: embeddings, RAG híbrido, ficha tipada y lotes del job nocturno.

Módulo hermano de ``config/settings.py`` (P3 «Los dos módulos-dios»): ``Settings``
hereda de esta clase, así que los nombres de las variables de entorno y el
acceso (``settings.PLIEGO_FACTS_MODEL``) son los de siempre.

Sin ``model_config`` propio, por lo mismo que ``config/settings_resumen.py``.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class PliegosSettings(BaseSettings):
    """Embeddings de ``documento_chunks``, /ask híbrido y fases de ``documentos_embeddings``."""

    # ── Embeddings / NLP ─────────────────────────────────────────────────
    # Modelo sentence-transformers a usar. Cambiar a un modelo multilingual para
    # soporte completo de idiomas adicionales (PT, FR, DE, IT, etc.)
    # Opciones recomendadas:
    #   "paraphrase-multilingual-MiniLM-L12-v2"   (~400 MB, rápido)
    #   "paraphrase-multilingual-mpnet-base-v2"    (~1.1 GB, mejor calidad)
    EMBEDDING_MODEL: str = "paraphrase-multilingual-MiniLM-L12-v2"
    # Versión lógica de los embeddings persistidos (documento_chunks) — si
    # cambia, se re-embebe. (El índice FAISS al que aludía originalmente se
    # retiró en 2026-07.)
    EMBEDDING_VERSION: str = "v1"

    # Extracción tipada de ficha del pliego. Requiere credencial para el modelo
    # seleccionado; se activa de forma explícita para no generar gasto por el
    # mero despliegue de la migración.
    PLIEGO_FACTS_ENABLED: bool = False
    # Extraer la ficha del pliego en background al abrir una oportunidad, si no
    # existe todavía. Es la «demanda real» que el lote nocturno no puede
    # adivinar: quien convierte un expediente en pursuit va a abrir la pestaña
    # Pliego hoy. Gasto acotado a un LLM por pursuit nuevo, y sólo si no había
    # ficha; se apaga sin tocar el job nocturno.
    PLIEGO_FACTS_ON_PURSUIT: bool = True
    # Mantener sincronizado con llm.client.DEFAULT_MODEL (lo comprueba
    # tests/test_llm_client.py). Los dos primeros valores acabaron en 410 al
    # retirarlos NVIDIA: deepseek-v4-pro el 2026-08-07 y deepseek-v4-flash-0731
    # el 2026-09-21; el tercero, nemotron-3-super, en 404 el 2026-10-20 sin
    # salir del catálogo (issue #523). La variable de repo del mismo nombre, si
    # existe, pisa este default en pliegos.yml: al cambiarlo, revisar también
    # `gh variable list`.
    PLIEGO_FACTS_MODEL: str = "nvidia/nemotron-3-ultra-550b-a55b"
    # Tamaños de lote por fase del job scheduler/jobs/documentos_embeddings.py.
    # pliegos.yml propaga REDIS_URL desde el secret del mismo nombre; si el
    # secret no está definido, el gate de presupuesto LLM arranca de 0 en cada
    # corrida y el tope real del batch de facts es este tamaño de lote, no un
    # presupuesto acumulado (documentado, no un bug).
    PLIEGO_FETCH_BATCH: int = 300
    PLIEGO_EMBED_BATCH: int = 100
    PLIEGO_FACTS_BATCH: int = 25
    # Tope de reloj por fase del mismo job, en segundos (0 = sin tope). El lote
    # por número no acota la duración: 300 documentos tardaron de 17 a 37 min
    # en septiembre de 2026 y 100 embeddings de 15 a más de 25, así que del run
    # #65 (2026-09-15) al #73 (2026-09-23) pliegos.yml se canceló nueve noches
    # seguidas por su `timeout-minutes` sin llegar a las fichas, a tech_signal
    # ni a la alerta de `run_cli`. Lo que no cabe en el tope se queda para el
    # lote siguiente (`aplazados` en el resumen) y las fases de después corren
    # siempre.
    PLIEGO_FETCH_MAX_SECONDS: int = 1200
    PLIEGO_EMBED_MAX_SECONDS: int = 900
    # 30 min desde tender-facts-v6 (2026-09-28): con contexto de ~16k tokens y
    # salida de hasta 8k, cada ficha tarda de 40 a 110 s, y los 10 min de antes
    # solo daban para 6-10 fichas por noche frente a un lote de 25.
    PLIEGO_FACTS_MAX_SECONDS: int = 1800
    # Días entre reintentos de una ficha `failed` por un fallo del proveedor
    # (401, modelo retirado, respuesta vacía, tope de reloj) con la versión
    # vigente del extractor. Los demás fallos no esperan a esto: los de una
    # versión anterior se reintentan una vez y los de los documentos cuando
    # estos cambian (`TenderFactSheetsRepository.list_pending_licitaciones`).
    # Los reintentos salen del mismo `PLIEGO_FACTS_BATCH`: no suben el gasto.
    PLIEGO_FACTS_REINTENTO_DIAS: int = 7
    # Tamaño del lote de licitaciones puntuadas por corrida de la fase de
    # señal de tecnología (keywords sobre el texto del pliego).
    PLIEGO_TECH_SIGNAL_BATCH: int = 500
    # Score mínimo (matched_terms ponderado por tipo de documento) para que
    # una señal de pliego entre al merge hacia ml_tecnologias/licitacion_tecnologia_score.
    PLIEGO_TECH_MIN_SCORE: float = 0.5
