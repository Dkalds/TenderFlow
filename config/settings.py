"""Configuración global del proyecto — basada en pydantic-settings."""

from __future__ import annotations

import ipaddress
import warnings
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.scoring_weights import validate_scoring_weights

_ROOT = Path(__file__).resolve().parent.parent


def _extract_sslmode(url: str) -> str | None:
    """Devuelve el valor de ``sslmode`` de una DATABASE_URL, o None si no está.

    Robusto frente a passwords con caracteres especiales: solo parsea la query
    string (tras ``?``). Devuelve el valor en minúsculas.
    """
    from urllib.parse import parse_qs, urlsplit

    values = parse_qs(urlsplit(url).query).get("sslmode")
    if not values:
        return None
    return values[-1].strip().lower()


# Hosts sin red externa que interceptar — sslmode no aporta nada real ahí.
_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1"}

# Techo por consulta para los perfiles que no sirven HTTP (ver
# ``Settings._relax_batch_statement_timeout``). Cinco minutos cubre con margen
# la consulta batch más lenta medida (76 s) sin dejar a un job colgado media
# hora contra la base de producción.
_BATCH_STATEMENT_TIMEOUT_MS = 300_000


def _extract_host(url: str) -> str | None:
    """Devuelve el hostname de una DATABASE_URL, o None si no se puede parsear."""
    from urllib.parse import urlsplit

    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


# En entornos donde el paquete se instala en site-packages (e.g. despliegues gestionados),
# _ROOT apuntaría a un directorio sin permisos de escritura.  Usamos un
# directorio escribible como fallback.
_DEFAULT_DATA_DIR = _ROOT / "data"
if "site-packages" in str(_ROOT):
    _DEFAULT_DATA_DIR = Path("/tmp/licitaciones_data")  # noqa: S108


class Settings(BaseSettings):
    """Todas las variables de entorno del proyecto, validadas al arrancar."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Entorno ──────────────────────────────────────────────────────────
    # ENV describe **qué datos** toca el proceso (dev/staging/prod).
    # APP_PROFILE describe **qué componentes** arranca. Son ejes ortogonales:
    # el scraper del cron toca datos de producción (ENV=prod) pero no sirve
    # HTTP, así que no necesita SIGNING_KEY ni REDIS_URL. Antes ambos ejes
    # viajaban en ENV, lo que obligaba al cron a declarar ENV=dev contra la BD
    # de producción y desactivaba de paso validators que sí le aplicaban
    # (ver el fix de sslmode en _validate_prod_database_ssl).
    ENV: Literal["dev", "staging", "prod"] = "prod"
    APP_PROFILE: Literal["api", "worker", "scraper"] = "api"

    # ── Rutas ────────────────────────────────────────────────────────────
    DATA_DIR: Path = _DEFAULT_DATA_DIR
    # VESTIGIAL (ADR-021): ya no apunta a ninguna BD — SQLite se retiró y el
    # único motor es Postgres vía DATABASE_URL. Sobrevive porque lo leen los
    # caminos DuckDB/backup pendientes de migrar (`db/analytics.py`,
    # `scripts/restore_db.py`), documentados como ítems abiertos del backlog.
    # **No usar en código nuevo.**
    DB_PATH: Path | None = None  # default calculado en validator
    DOWNLOADS_DIR: Path | None = None

    # ── ML ───────────────────────────────────────────────────────────────
    # Umbral de confianza para clasificar como SAP sin keywords (0.0-1.0)
    ML_CONFIDENCE_THRESHOLD: float = 0.70
    # β para F-beta en el threshold sweep. β>1 favorece recall (FN costoso),
    # β<1 favorece precision. 1.5 prioriza ligeramente recall (perder una
    # licitación SAP cuesta más que una falsa alerta).
    ML_FBETA: float = 1.5
    # Si True, usar TimeSeriesSplit (sin shuffle) cuando hay fecha_publicacion.
    # Refleja mejor la performance esperada en producción (datos futuros).
    ML_USE_TIMESERIES_CV: bool = True
    # Rangos de incertidumbre para la cola de active learning (P(SAP) ∈ [lo, hi]).
    ML_UNCERTAINTY_LO: float = 0.30
    ML_UNCERTAINTY_HI: float = 0.70

    # ── ML Multi-Tecnología (OneVsRest sobre la columna `tecnologia`) ─────
    # Master switch: si False, el pipeline y el scheduler no usan el clasificador
    # multi-tecnología; ml_proba (=P(SAP)) sigue gobernando el gating.
    # Activado en producción (2026-05-23) — requiere TechnologyClassifier en disco.
    # Si el modelo no existe, el pipeline cae silenciosamente a modo keywords.
    ML_TECH_ENABLED: bool = True
    # Prácticas activas para gating extendido. Por defecto sólo SAP, lo que
    # equivale al comportamiento histórico (no se aceptan licitaciones por
    # otras tecnologías hasta que la práctica correspondiente se active).
    ML_TECH_GATING_PRACTICES: list[str] = ["SAP"]
    # Threshold por defecto cuando una tecnología no tiene threshold optimizado.
    ML_TECH_DEFAULT_THRESHOLD: float = 0.50
    # Overrides por tecnología (en JSON via ENV). Si está vacío, se usan los
    # thresholds aprendidos en train() y persistidos en el pickle del modelo.
    ML_TECH_THRESHOLDS: dict[str, float] = {}
    # Tiers según número de positivos por tecnología:
    #   - ml_ready  : ≥ MIN_POS_READY   → LR calibrada normal
    #   - fragile   : ≥ MIN_POS_FRAGILE → LR con C reducido + threshold conservador
    #   - rules     : por debajo        → fallback a keywords curadas
    ML_TECH_MIN_POS_READY: int = 50
    ML_TECH_MIN_POS_FRAGILE: int = 20
    # Regularización LogReg para tier frágil (más fuerte = menos overfit).
    ML_TECH_FRAGILE_C: float = 0.3
    # Precisión mínima exigida al elegir threshold del tier frágil.
    ML_TECH_FRAGILE_MIN_PRECISION: float = 0.70
    # Reentrenamiento semanal automático (cron en scheduler.loop).
    # Activado (2026-05-23) — si hay ≥50 nuevos feedbacks, reentrenar y evaluar.
    ML_TECH_AUTO_RETRAIN: bool = True
    # Si True, train() ejecuta RandomizedSearchCV para buscar hiperparámetros.
    ML_TUNE_ON_TRAIN: bool = False
    # Si True, usa sentence-transformers embeddings como feature adicional en el
    # pipeline ML. Requiere: pip install licitaciones-sap[ml-embeddings]
    ML_USE_EMBEDDINGS: bool = False
    # Golden set etiquetado a mano (JSONL) para evaluación honesta de recall
    # contra labels humanas, independiente del filtro de keywords. Ruta relativa
    # al repo o absoluta. Ver services/ml_eval.py.
    ML_GOLDEN_SET_PATH: str = "tests/fixtures/golden_set.jsonl"
    # PU learning (Positive-Unlabeled): si True, los negativos "ambiguos" (CPV
    # TI 48/72 sin keywords — potenciales SAP no detectados) reciben menor peso
    # de muestra en el entrenamiento, en vez de tratarse como negativos de
    # confianza plena. Reduce el sesgo de aprender el filtro de keywords como
    # ground truth. Ver scraper/ml_pipeline._build_dataset.
    ML_PU_LEARNING: bool = False
    # Peso de muestra para los negativos ambiguos cuando ML_PU_LEARNING=True.
    ML_PU_UNLABELED_WEIGHT: float = 0.5
    # Costos relativos para el tuning de threshold sensible a coste. Un falso
    # negativo (perder una licitación SAP real) cuesta más que un falso positivo
    # (revisar una falsa alerta). El golden tuning usa beta = sqrt(FN/FP).
    ML_COST_FN: float = 3.0
    ML_COST_FP: float = 1.0
    # Si True, el threshold final se ajusta sobre el golden set (labels humanas)
    # con costos reales, en lugar de solo sobre el test split (labels derivadas
    # de keywords). Ver services/ml_eval.tune_threshold_on_golden.
    ML_TUNE_THRESHOLD_ON_GOLDEN: bool = True
    # Calibración externa: si True, el pipeline base se construye SIN
    # CalibratedClassifierCV interno y la calibración + tuning de umbral sensible
    # a coste la aplica services.threshold_tuning.calibrate_and_tune (una sola
    # capa, sin doble calibración). Si False (default), el pipeline calibra
    # internamente. Ver SAPClassifier.__init__.
    ML_USE_CALIBRATION: bool = False
    # Si True, _augment_text emite un token estable del órgano de contratación
    # (hash a bucket), permitiendo al modelo aprender que ciertos órganos compran
    # SAP de forma recurrente. Off por defecto para evitar training-serving skew
    # hasta que todos los call sites de predict propaguen el órgano. Ver
    # scraper/ml_pipeline._augment_text.
    ML_USE_ORGANO_FEATURE: bool = False
    # Hash SHA256 fijado del modelo (out-of-band). Si se define, load() y
    # ensure_downloaded() verifican el .pkl contra este valor ADEMÁS del checksum
    # .sha256 co-ubicado. Defensa contra un GitHub Release comprometido (donde
    # .pkl y .sha256 podrían sustituirse a la vez, y joblib.load ejecuta código
    # arbitrario). Vacío = sin pin. Ver scraper/ml_classifier.SAPClassifier.load.
    ML_MODEL_SHA256: str = ""
    # Hash SHA256 fijado (out-of-band) para el TechnologyClassifier
    # (data/models/tech_classifier.pkl). Mismo propósito y semántica que
    # ML_MODEL_SHA256. Vacío = sin pin. Ver
    # scraper.tech_classifier.TechnologyClassifier.load.
    ML_TECH_MODEL_SHA256: str = ""
    # Hash SHA256 fijado (out-of-band) para BajaModel
    # (data/models/baja_model.pkl). Vacío = sin pin. Ver
    # services.ml.baja_model.BajaModel.load.
    ML_BAJA_MODEL_SHA256: str = ""
    # Hash SHA256 fijado (out-of-band) para RetencionModel
    # (data/models/retencion_model.pkl). Vacío = sin pin. Ver
    # services.ml.retencion_model.RetencionModel.load.
    ML_RETENCION_MODEL_SHA256: str = ""

    # ── Modelos predictivos (Fase 6, RFC 20260611-2) ─────────────────────
    # Si True, el re-entrenamiento mensual activa la versión nueva
    # automáticamente cuando bate todas las métricas vs la activa (criterios
    # del RFC). Por defecto la activación es manual (model_registry).
    ML_PRED_AUTO_ACTIVATE: bool = False

    # Conformaliza el intervalo p10-p90 del modelo de baja (split-CQR) sobre un
    # bloque temporal que el ajuste no vio: la cobertura del 80% se cumple por
    # construcción en vez de depender de que los tres cuantiles salgan bien
    # calibrados por su cuenta. Ver services.ml.baja_model._offset_conformal.
    ML_BAJA_CONFORMAL: bool = True
    # Cortes de validación rolling-origin del modelo de baja. 1 reproduce el
    # holdout único anterior.
    ML_BAJA_FOLDS: int = 3
    # Combinaciones de hiperparámetros a explorar (0 = usar solo la base fija).
    ML_BAJA_SEARCH_COMBOS: int = 8
    # Vida media en meses del peso por recencia de las filas de entrenamiento.
    # 0 desactiva el decaimiento (pesos uniformes, comportamiento anterior).
    ML_BAJA_HALFLIFE_MESES: float = 18.0

    # ── DB / Upsert ──────────────────────────────────────────────────────
    # Tamaño de chunk para upsert_licitaciones_with_history. Cada chunk
    # se ejecuta en su propia transacción, liberando el write lock entre chunks.
    UPSERT_CHUNK_SIZE: int = 500

    # ── Secrets ───────────────────────────────────────────────────────────
    # TTL (segundos) para el cache in-process de secretos. Tras expirar, el
    # próximo get_secret() re-consulta el backend (vault/env). Permite que la
    # rotación de secretos en vault se propague sin reiniciar el proceso.
    # 0 = sin cache (re-fetch siempre). Default 300s (5 min).
    SECRETS_CACHE_TTL_SECONDS: int = 300

    # ── Resiliencia ───────────────────────────────────────────────────────
    # Circuit breaker: backoff exponencial entre aperturas del circuito
    BREAKER_BASE_TIMEOUT: int = 60  # segundos — primer timeout tras apertura
    BREAKER_MAX_TIMEOUT: int = 1800  # segundos — techo del backoff (30 min)

    # ── OpenTelemetry ─────────────────────────────────────────────────────
    # Si está vacío, el tracing opera en modo NoOp (sin overhead)
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = "tenderflow"
    # Fracción de trazas a muestrear [0.0-1.0]. Las trazas con error se
    # muestrean siempre independientemente de este valor.
    # Default 0.1 (10%) — suficiente para debugging en un sistema de scraping
    # con volumen moderado. Ajustar a 0.01 en entornos de alto tráfico.
    OTEL_SAMPLE_RATIO: float = 0.1

    # ── OAuth ────────────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: SecretStr = SecretStr("")
    OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/oauth/google/callback"
    OAUTH_ALLOWED_EMAILS: str = ""
    OAUTH_ALLOWED_DOMAINS: str = ""
    OAUTH_ADMIN_EMAILS: str = ""
    # Clave independiente para firmar tokens CSRF/OAuth state (HMAC-SHA256).
    # Si no se configura, se deriva de GOOGLE_CLIENT_SECRET como fallback.
    # En producción configura un valor aleatorio de 32+ caracteres:
    #   python -c "import secrets; print(secrets.token_hex(32))"
    # Orígenes CORS permitidos en prod (lista separada por comas, vacío = bloquear todo)
    # En dev se usa "*" automáticamente.
    # Ej: "https://app.example.com,https://api.example.com"
    CORS_ALLOWED_ORIGINS: str = ""

    # Secreto HMAC para hashear API keys (32+ chars). Si vacío usa SHA-256 plain.
    # Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"
    API_HMAC_SECRET: SecretStr = SecretStr("")
    # Las API keys nuevas son de mínimo privilegio y tienen caducidad. La
    # creación de una key con ``*`` debe ser una decisión explícita de un admin.
    API_KEY_DEFAULT_SCOPES: str = "data:read"
    API_KEY_DEFAULT_TTL_DAYS: int = 90
    API_KEY_MAX_TTL_DAYS: int = 365
    # Límite global del RateLimitMiddleware. `api/app.py` los leía con
    # `getattr(settings, ...)` y `Settings` no los declaraba: con
    # `extra="ignore"`, exportar la variable no hacía nada y el límite era
    # siempre 120/60s, pese a que docs/runbooks/rate-limit-reset.md los
    # documenta como palanca de operación. Declararlos los vuelve reales.
    API_RATE_LIMIT_MAX_CALLS: int = 120
    API_RATE_LIMIT_WINDOW_SECONDS: float = 60.0
    # Operaciones irreversibles requieren autenticación reciente; si la cuenta
    # usa MFA también se exige una elevación reciente de segundo factor.
    SENSITIVE_ACTION_MAX_AGE_SECONDS: int = 900
    MFA_STEP_UP_MAX_AGE_SECONDS: int = 900
    MFA_MAX_FAILURES: int = 5
    MFA_FAILURE_WINDOW_SECONDS: int = 300
    # Las claves de idempotencia son datos de corta vida: no deben convertirse
    # en una caché permanente de respuestas ni secretos de integración.
    IDEMPOTENCY_TTL_SECONDS: int = 86_400

    SIGNING_KEY: SecretStr = SecretStr("")
    # Firma independiente de la cadena de auditoría. No compartir con tokens.
    AUDIT_HMAC_KEY: SecretStr = SecretStr("")

    # Clave maestra para derivar secretos de webhook (HMAC-SHA256).
    # Si vacío, se deriva de SIGNING_KEY como fallback.
    # Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"
    WEBHOOK_SIGNING_KEY: SecretStr = SecretStr("")

    # Clave Fernet para cifrar secretos TOTP at-rest. Obligatoria en prod.
    # Genera una con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    TOTP_ENCRYPTION_KEY: SecretStr = SecretStr("")

    # ── Postgres / Supabase (ADR-016, F3) ────────────────────────────────
    # Cuando DATABASE_URL está definida tiene precedencia sobre SQLite local.
    # Formato: postgresql://user:pass@host:5432/db?sslmode=require  # pragma: allowlist secret
    # En Supabase: usar Supavisor session pooler (puerto 5432) para compatibilidad
    # con GH Actions (IPv4-only) y evitar conflictos con PREPARE.
    DATABASE_URL: SecretStr = SecretStr("")

    # Ruta al certificado CA raíz de Supabase (Dashboard → Database → SSL).
    # Necesario para usar ``sslmode=verify-full`` (verifica cadena + hostname del
    # servidor, previene MITM). No es un secreto (cert público). Si está vacío y
    # el DSN pide verify-full, psycopg buscará la CA del sistema.
    DATABASE_SSL_ROOT_CERT: str = ""

    # Timeouts server-side aplicados a cada conexión del pool Postgres. Protegen
    # contra queries descontroladas o transacciones idle que clavan una conexión
    # y saturan el pool (pequeño). En milisegundos; 0 = sin límite (no recomendado).
    #
    # El default vale para el perfil ``api``, que es donde el pool es un recurso
    # compartido y escaso. Los perfiles batch lo reciben más alto por
    # ``_relax_batch_statement_timeout``: ver ese validator antes de asumir que
    # 30 s es el valor efectivo en un job.
    DB_STATEMENT_TIMEOUT_MS: int = 30_000
    DB_IDLE_TX_TIMEOUT_MS: int = 60_000
    # Timeout (segundos) para establecer la conexión TCP/TLS al pooler.
    DB_CONNECT_TIMEOUT: int = 10

    # ── Observabilidad ───────────────────────────────────────────────────
    LOG_FORMAT: str = ""
    ALERT_MIN_LEVEL: str = "warn"
    ALERT_EMAIL_TO: str = ""
    ALERT_SMTP_USER: str = ""
    ALERT_SMTP_PASSWORD: SecretStr = SecretStr("")
    ALERT_SMTP_HOST: str = "smtp.gmail.com"
    ALERT_SMTP_PORT: int = 587

    # ── Grafana ─────────────────────────────────────────────────────────
    GF_SECURITY_ADMIN_PASSWORD: SecretStr = SecretStr("")

    # ── Anomaly detection ────────────────────────────────────────────────
    # Activar detección de anomalías en el scheduler
    ANOMALY_ALERT_ENABLED: bool = True
    # Desviaciones estándar para considerar un importe anómalo vs. histórico del órgano
    ANOMALY_IMPORTE_SIGMA: float = 2.0
    # % de baja sobre el presupuesto a partir del cual se alerta (baja temeraria)
    ANOMALY_BAJA_THRESHOLD: float = 80.0
    # Factor vs. media diaria de los últimos 30d para considerar spike de publicaciones
    ANOMALY_SPIKE_FACTOR: float = 3.0

    # ── Base de datos ─────────────────────────────────────────────────────
    DB_POOL_SIZE: int = 5
    # Segundos de espera por una conexión libre antes de fallar. Sin este
    # límite del lado cliente, una petición espera indefinidamente cuando el
    # pool está agotado y la saturación se manifiesta como cuelgue, no como
    # error medible (ver `db_pool_acquire_timeout_total`).
    DB_POOL_TIMEOUT: float = 10.0
    # Tamaño del pool de LECTURA (`connect_read`). 0 = mismo que DB_POOL_SIZE.
    # Son pools separados porque el modo solo-lectura se fija en la sesión.
    DB_READ_POOL_SIZE: int = 0
    # Reciclado de conexiones (segundos). `max_idle` mantiene las ociosas por
    # debajo del idle-timeout del pooler de Supabase, que si no las corta y el
    # pool entrega una conexión muerta; `max_lifetime` recicla también la que
    # sostiene `min_size`. 0 desactiva cada uno.
    DB_POOL_MAX_IDLE_SECONDS: float = 120.0
    DB_POOL_MAX_LIFETIME_SECONDS: float = 1800.0

    # ── Scraper ──────────────────────────────────────────────────────────
    REQUEST_TIMEOUT: int = 30
    REQUEST_DELAY_SECONDS: float = 1.5
    MAX_DOWNLOAD_SIZE_BYTES: int = 400 * 1024 * 1024
    MAX_XML_SIZE_BYTES: int = 150 * 1024 * 1024
    DAILY_MAX_PAGES: int = 50
    BACKFILL_MAX_WORKERS: int = 3
    # Límite de tamaño para un adjunto individual (pliego), plan Pliegos+RAG F7.
    # Mucho más chico que MAX_DOWNLOAD_SIZE_BYTES (pensado para ZIPs mensuales
    # con miles de entries) — un PDF de pliego legítimo rara vez supera 50 MB.
    MAX_DOCUMENT_SIZE_BYTES: int = 50 * 1024 * 1024
    MAX_DOCUMENT_PAGES: int = 250
    MAX_DOCUMENT_TEXT_CHARS: int = 2_000_000
    # In production PDF parsing runs in a disposable child process. A malformed
    # document cannot monopolize the scheduler process indefinitely.
    DOCUMENT_EXTRACTION_TIMEOUT_SECONDS: int = 30
    DOCUMENT_ALLOWED_HOSTS: str = "contrataciondelestado.es,*.contrataciondelestado.es"
    WEBHOOK_ALLOWED_HOSTS: str = ""
    ALLOW_SELF_REGISTRATION: bool = False

    # ── Conectores autonómicos / TACRC (RFC 20260611-1, Fase 5) ─────────
    # Dataset Socrata de publicaciones de la PSCP en el portal de
    # transparencia de la Generalitat. El id ybgg-dgi6 ("Contractació
    # pública a Catalunya: publicacions a la PSCP") está verificado contra
    # el portal oficial; los NOMBRES DE CAMPO siguen sin validar contra la
    # API viva — correr `python scripts/probe_pscp.py --dataset ybgg-dgi6`
    # antes del primer backfill y ajustar _FIELD_CANDIDATES si difieren.
    PSCP_DOMAIN: str = "analisi.transparenciacatalunya.cat"
    PSCP_DATASET_ID: str = "ybgg-dgi6"
    # App token Socrata opcional (solo necesario si aparece rate limiting).
    PSCP_APP_TOKEN: SecretStr = SecretStr("")
    # ── F2: Retrofit PLACSP → Connector (ADR-009) ────────────────────────
    # Cuando True, run_daily_pipeline y run_bulk_pipeline usan PlacspAtomConnector
    # / PlacspBulkConnector en lugar del pipeline legacy (scraper/pipeline.py).
    # Activado 2026-07-11 tras paridad verde sobre datos reales del feed ATOM
    # (196 licitaciones + 166 adjudicaciones idénticas campo a campo entre
    # ambos caminos; ver ADR-009). Rollback: poner False — el pipeline legacy
    # sigue intacto (DEPRECATED, no borrado). Retirar el flag y el legacy tras
    # ≥1 ciclo semanal estable en producción.
    PLACSP_CONNECTOR_ENABLED: bool = True
    # Índice de resoluciones TACRC (Ministerio de Hacienda).
    #
    # URL validada con `python -m scraper.connectors.tacrc --check` (2026-06-11):
    # - BuscadordeResoluciones.aspx → SharePoint JS-rendered, 0 resoluciones
    #   parseadas con lxml (sin headless browser). NO usar como default.
    # - Resoluciones-Pleno.aspx → HTML estático con 17 PDFs embebidos;
    #   parser extrae 17 resoluciones. VALIDADO ✓
    #
    # Resoluciones-Pleno cubre solo resoluciones del Pleno (doctrinales); las
    # resoluciones individuales de recurso quedan pendientes de otro índice.
    # Para cobertura completa, configurar TACRC_INDEX_URL por entorno.
    TACRC_INDEX_URL: str = (
        "https://www.hacienda.gob.es/es-ES/Areas%20Tematicas/Contratacion/"
        "TACRC/Paginas/Resoluciones-Pleno.aspx"
    )

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

    # ── Scoring de oportunidades ─────────────────────────────────────────
    # Pesos por dimensión (enteros, deben sumar 100). Validados al arrancar por
    # shared/scoring_weights.py, el mismo validador que aplica el perfil de
    # usuario.
    #
    # `senal_tecnica` (2026-08) mide cuán confirmada está la tecnología en el
    # pliego real y en el clasificador. Los 10 puntos salen de `importe` y
    # `competencia`, que son las dos señales más ruidosas del reparto: una
    # normaliza contra los percentiles de ~1,6 k importes y la otra contra
    # medias por CPV-4 con muestras de tres expedientes. `margen` se deja
    # intacta porque es la única que viene de una predicción por licitación.
    #
    # Overridable via ENV como JSON:
    #   SCORING_WEIGHTS='{"importe":20,"plazo":15,"competencia":20,"margen":20,"afinidad":15,"senal_tecnica":10}'
    SCORING_WEIGHTS: dict[str, int] = {
        "importe": 20,
        "plazo": 15,
        "competencia": 20,
        "margen": 20,
        "afinidad": 15,
        "senal_tecnica": 10,
    }
    # Keywords de afinidad configurables por el usuario (casefold-substring sobre título).
    # Si está vacía, la dimensión afinidad se omite del desglose y su peso se
    # redistribuye proporcionalmente entre las demás dimensiones.
    # Overridable via ENV como JSON:
    #   SCORING_AFINIDAD_KEYWORDS='["consultoría","mantenimiento"]'
    SCORING_AFINIDAD_KEYWORDS: list[str] = []

    # ── API REST ─────────────────────────────────────────────────────────
    # Hilos del threadpool de anyio, donde corre TODO el trabajo síncrono de la
    # API (los ~104 `run_db` y los handlers `def`). Estuvo fijado a 4 desde un
    # incidente de CPU en Render Free: el límite era correcto para la analítica
    # pandas pero castigaba por igual a las lecturas IO-bound, que solo esperan
    # red — con 4 hilos y un pool de 5 conexiones, el techo de la API era de 4
    # peticiones concurrentes. Ahora el trabajo CPU-bound tiene su propio carril
    # (API_CPU_BOUND_TOKENS) y este límite puede respirar.
    API_THREADPOOL_TOKENS: int = 24
    # Bulkheads dedicados (subconjuntos del threadpool anterior).
    API_CPU_BOUND_TOKENS: int = 2
    API_ML_TOKENS: int = 2
    # TTL de la caché de proceso del clasificador ML. Cubre el caso
    # multi-worker: `/models/{name}/activate` invalida el proceso que atiende
    # la petición, y los demás recargan al vencer este plazo. 0 = sin recarga
    # por tiempo (solo invalidación explícita).
    API_MODEL_CACHE_TTL_SECONDS: float = 300.0
    # IPs (o rangos) que pueden acceder a /metrics sin API key (separadas por coma).
    # Por defecto solo loopback. En producción añadir la IP del servidor Prometheus.
    # Ej: "127.0.0.1,10.0.0.5,10.0.0.6"
    METRICS_ALLOWED_IPS: str = "127.0.0.1"
    # IPs (o rangos CIDR) del reverse proxy cuyo ``X-Forwarded-For`` se considera
    # confiable, separadas por coma. La consume uvicorn (`--forwarded-allow-ips`,
    # que reescribe la IP del peer con la cabecera) y api.middleware
    # ._trusted_client_ip, del que dependen el rate limiting, el lockout de login
    # y la IP que queda registrada en el audit log.
    #
    # El comodín "*" hace que se acepte la cabecera venga de donde venga: el
    # cliente pasa a elegir su propia IP y las tres defensas anteriores dejan de
    # discriminar entre atacantes. Por eso el default es loopback y
    # _validate_prod_forwarded_allow_ips impide arrancar con "*" en prod/staging.
    #
    # Hasta 2026-08-02 este campo no estaba declarado y model_config usa
    # extra="ignore": la variable de entorno se descartaba en silencio y el
    # getattr de api/middleware.py caía siempre al default. Si alguien la vuelve
    # a quitar, la defensa deja de ser configurable sin que nada falle.
    FORWARDED_ALLOW_IPS: str = "127.0.0.1"

    # ── Cache (Redis opcional) ────────────────────────────────────────────
    # Si se deja vacío se usa cache en memoria por proceso (default).
    # Formato: redis://[:password@]host[:port][/db]
    REDIS_URL: str = ""
    # Contraseña de Redis. En producción debe coincidir con --requirepass del servidor.
    # Genera una con: python -c "import secrets; print(secrets.token_hex(32))"
    REDIS_PASSWORD: SecretStr = SecretStr("")
    # Token para la REST API de Upstash (GET https://host/PING, puerto 443).
    # Necesario cuando el puerto TCP 6380 está bloqueado (redes domésticas/corporativas).
    # Cópialo desde Upstash Console → tu base de datos → "Connect" → REST API Token.
    REDIS_REST_TOKEN: str = ""

    # ── Job dedicado de watchlist_rules (plan Pliegos+RAG, C2a) ────────────
    # Default False: la pipeline canónica (scheduler/pipeline_runs.py::
    # _run_watchlist_notify) ya llama a check_rules_and_notify() tras cada
    # ingesta. Este job existe para el plano APScheduler/Docker (ADR-012) —
    # activarlo solo si ese plano es el dueño de la orquestación, para no
    # correr la evaluación de reglas dos veces (la idempotencia de
    # user_notifications limita el daño a not-doble-notificación, pero no
    # el trabajo duplicado de evaluar las reglas).
    WATCHLIST_RULES_JOB_ENABLED: bool = False

    # ── RAG híbrido sobre pliegos (plan Pliegos+RAG, F9) ───────────────────
    # Default False: /ask sigue siendo FTS puro hasta activarlo explícitamente
    # (requiere Postgres + extra [ml] instalado + documento_chunks poblada).
    # Con el flag off, search_for_ask() es idéntico byte-a-byte al camino
    # anterior — PR mergeable sin riesgo.
    RAG_HYBRID_ENABLED: bool = False
    # Extracción tipada de ficha del pliego. Requiere credencial para el modelo
    # seleccionado; se activa de forma explícita para no generar gasto por el
    # mero despliegue de la migración.
    PLIEGO_FACTS_ENABLED: bool = False
    # Mantener sincronizado con llm.client.DEFAULT_MODEL: el valor anterior
    # (deepseek-v4-pro) quedó EOL en NVIDIA el 2026-08-07 y devolvía 410.
    PLIEGO_FACTS_MODEL: str = "deepseek-ai/deepseek-v4-flash-0731"
    # Tamaños de lote por fase del job scheduler/jobs/documentos_embeddings.py.
    # pliegos.yml no propaga REDIS_URL, así que el gate de presupuesto LLM
    # arranca de 0 en cada corrida -- el tope real del batch de facts es este
    # tamaño de lote, no un presupuesto acumulado (documentado, no un bug).
    PLIEGO_FETCH_BATCH: int = 300
    PLIEGO_EMBED_BATCH: int = 100
    PLIEGO_FACTS_BATCH: int = 25
    # Tamaño del lote de licitaciones puntuadas por corrida de la fase de
    # señal de tecnología (keywords sobre el texto del pliego).
    PLIEGO_TECH_SIGNAL_BATCH: int = 500
    # Score mínimo (matched_terms ponderado por tipo de documento) para que
    # una señal de pliego entre al merge hacia ml_tecnologias/licitacion_tecnologia_score.
    PLIEGO_TECH_MIN_SCORE: float = 0.5

    # ── LLM: presupuesto de gasto + timeout (RFC llm-dependencia-gestionada) ──
    # Tope de gasto del proveedor LLM por ventana (USD). <= 0 desactiva el límite.
    LLM_BUDGET_USD_DAILY: float = 5.0
    LLM_BUDGET_USD_MONTHLY: float = 50.0
    # El tope global protege la factura; el tope por usuario evita que una sola
    # cuenta consuma la ventana diaria de todos (denegación de servicio por
    # agotamiento de presupuesto). <= 0 lo desactiva, igual que sus hermanos.
    LLM_BUDGET_USD_DAILY_PER_USER: float = 1.0
    # monitor: superar el presupuesto solo alerta (métrica + warning), no corta.
    # enforce: /ask responde 429 sin llamar al proveedor. Default enforce: en
    # monitor los topes de arriba no son un límite de gasto, solo un indicador,
    # y la factura queda abierta. monitor sigue disponible para rodajes puntuales
    # (medir el consumo real antes de fijar un tope), pero es una elección
    # explícita y temporal, no el estado de reposo.
    LLM_BUDGET_MODE: Literal["monitor", "enforce"] = "enforce"
    # Timeout (s) esperando al LLM en /ask. Antes era env directo en ask.py;
    # el nombre del env var se mantiene, así que despliegues existentes siguen
    # funcionando sin cambios.
    ASK_LLM_TIMEOUT_SECONDS: float = 120.0

    # ── Validators ───────────────────────────────────────────────────────

    @model_validator(mode="after")
    def _validate_scoring_weights(self) -> Settings:
        # Misma regla que aplica el perfil de usuario en `PUT /me/profile`: los
        # dos caminos por los que entran pesos comparten validador para que no
        # puedan divergir (shared/scoring_weights.py).
        validate_scoring_weights(self.SCORING_WEIGHTS, source="SCORING_WEIGHTS")
        return self

    @field_validator("ML_CONFIDENCE_THRESHOLD", mode="before")
    @classmethod
    def _validate_ml_threshold(cls, v: object) -> float:
        val = float(v)  # type: ignore[arg-type]
        if not (0.0 <= val <= 1.0):
            raise ValueError("ML_CONFIDENCE_THRESHOLD debe estar entre 0.0 y 1.0")
        return val

    @field_validator("ML_TECH_DEFAULT_THRESHOLD", mode="before")
    @classmethod
    def _validate_ml_tech_default_threshold(cls, v: object) -> float:
        val = float(v)  # type: ignore[arg-type]
        if not (0.0 <= val <= 1.0):
            raise ValueError("ML_TECH_DEFAULT_THRESHOLD debe estar entre 0.0 y 1.0")
        return val

    @field_validator("OTEL_SAMPLE_RATIO", mode="before")
    @classmethod
    def _validate_otel_sample_ratio(cls, v: object) -> float:
        val = float(v)  # type: ignore[arg-type]
        if not (0.0 <= val <= 1.0):
            raise ValueError("OTEL_SAMPLE_RATIO debe estar entre 0.0 y 1.0")
        return val

    @field_validator("REQUEST_TIMEOUT", mode="before")
    @classmethod
    def _validate_request_timeout(cls, v: object) -> int:
        val = int(str(v))
        if val <= 0:
            raise ValueError("REQUEST_TIMEOUT debe ser > 0")
        return val

    @field_validator("ALERT_SMTP_PORT", mode="before")
    @classmethod
    def _validate_smtp_port(cls, v: object) -> int:
        val = int(str(v))
        if not (1 <= val <= 65535):
            raise ValueError("ALERT_SMTP_PORT debe estar entre 1 y 65535")
        return val

    @field_validator("DB_POOL_SIZE", mode="before")
    @classmethod
    def _validate_pool_size(cls, v: object) -> int:
        val = int(str(v))
        if val < 1:
            raise ValueError("DB_POOL_SIZE debe ser >= 1")
        return val

    @field_validator("API_THREADPOOL_TOKENS", mode="before")
    @classmethod
    def _validate_threadpool_tokens(cls, v: object) -> int:
        val = int(str(v))
        if val < 1:
            raise ValueError("API_THREADPOOL_TOKENS debe ser >= 1")
        return val

    @model_validator(mode="after")
    def _validate_ml_uncertainty_range(self) -> Settings:
        if self.ML_UNCERTAINTY_LO >= self.ML_UNCERTAINTY_HI:
            raise ValueError(
                f"ML_UNCERTAINTY_LO ({self.ML_UNCERTAINTY_LO}) debe ser menor que "
                f"ML_UNCERTAINTY_HI ({self.ML_UNCERTAINTY_HI})"
            )
        return self

    @model_validator(mode="after")
    def _set_derived_paths(self) -> Settings:
        if self.DB_PATH is None:
            self.DB_PATH = self.DATA_DIR / "licitaciones.db"
        if self.DOWNLOADS_DIR is None:
            self.DOWNLOADS_DIR = self.DATA_DIR / "downloads"
        return self

    # ── Helpers de gating de validators ──────────────────────────────────
    # Regla: los validators se agrupan por *lo que el proceso hace*, no por
    # el entorno. `_serves_http` marca los secretos que solo tienen sentido
    # cuando el proceso expone la API (CSRF, API keys, CORS, caché Redis).
    # Los validators de BD, alertas y contraseñas aplican a todos los perfiles.

    @property
    def _is_prod_data(self) -> bool:
        """True si el proceso toca datos de producción o staging."""
        return self.ENV in ("prod", "staging")

    @property
    def _serves_http(self) -> bool:
        """True si el proceso expone la API HTTP (perfil ``api``)."""
        return self.APP_PROFILE == "api"

    @model_validator(mode="after")
    def _relax_batch_statement_timeout(self) -> Settings:
        """Sube el techo de tiempo por consulta en los perfiles que no sirven HTTP.

        Los 30 s del default protegen un recurso que solo existe en la API: un
        pool de 12 conexiones compartido por todas las peticiones, donde una
        consulta clavada se lleva por delante a endpoints que no calculan nada.
        Un job de GitHub Actions no tiene esa restricción —proceso propio, una
        tarea, y su propio timeout de workflow— y sí tiene consultas que
        legítimamente pasan de 30 s: la auditoría diaria de
        ``domain-truth.yml`` mide 76 s, y el precálculo de KPIs agrega
        ``adjudicaciones`` entera en unos 42 s.

        Se deriva de ``APP_PROFILE`` en vez de declararlo en cada workflow
        porque es el eje que el proyecto ya usa para esto (los ocho workflows
        que tocan la BD declaran ``scraper``, y Render declara ``api``), y así
        no depende de que nadie recuerde añadir una variable al octavo.

        Un valor explícito en el entorno gana siempre: ``model_fields_set``
        solo contiene los campos que llegaron de fuera, no los defaults.
        """
        if "DB_STATEMENT_TIMEOUT_MS" not in self.model_fields_set and not self._serves_http:
            self.DB_STATEMENT_TIMEOUT_MS = _BATCH_STATEMENT_TIMEOUT_MS
        return self

    @model_validator(mode="after")
    def _validate_prod_signing_key(self) -> Settings:
        if self._is_prod_data and self._serves_http and not self.SIGNING_KEY.get_secret_value():
            raise ValueError(
                "SIGNING_KEY es obligatorio en ENV=prod con APP_PROFILE=api para firmar tokens CSRF/OAuth. "
                'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return self

    @model_validator(mode="after")
    def _validate_prod_webhook_signing_key(self) -> Settings:
        """En producción, exigir WEBHOOK_SIGNING_KEY o SIGNING_KEY como fallback."""
        if self._is_prod_data and self._serves_http:
            wk = self.WEBHOOK_SIGNING_KEY.get_secret_value()
            sk = self.SIGNING_KEY.get_secret_value()
            if not wk and not sk:
                raise ValueError(
                    "WEBHOOK_SIGNING_KEY (o SIGNING_KEY como fallback) es obligatorio "
                    "en ENV=prod con APP_PROFILE=api para derivar secretos de webhook. "
                    'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
                )
        return self

    @model_validator(mode="after")
    def _validate_prod_egress_allowlists(self) -> Settings:
        """Exige allowlists para salidas que procesan contenido no confiable."""
        if self.ENV in ("prod", "staging"):
            if not self.DOCUMENT_ALLOWED_HOSTS:
                raise ValueError("DOCUMENT_ALLOWED_HOSTS es obligatorio en producción")
            if "*" in {host.strip() for host in self.WEBHOOK_ALLOWED_HOSTS.split(",")}:
                raise ValueError("WEBHOOK_ALLOWED_HOSTS no puede contener el comodín global '*'")
        return self

    @model_validator(mode="after")
    def _validate_prod_forwarded_allow_ips(self) -> Settings:
        """Impide confiar en el ``X-Forwarded-For`` de cualquier peer en producción.

        Con "*", uvicorn sobrescribe la IP del cliente con el primer elemento de
        la cabecera, que lo escribe el propio cliente (el proxy añade la IP real
        *detrás*). El atacante elige entonces qué IP ve la aplicación: el rate
        limiting y el lockout de login se esquivan rotando el valor, y la IP del
        audit log deja de ser evidencia de nada. Un valor vacío es igual de malo
        por la vía contraria: deja el campo sin configurar en un despliegue que
        sí está detrás de un proxy.
        """
        if not (self._is_prod_data and self._serves_http):
            return self
        entries = {ip.strip() for ip in self.FORWARDED_ALLOW_IPS.split(",") if ip.strip()}

        def _confia_en_todos(entrada: str) -> bool:
            """True si la entrada equivale a "confío en cualquier peer".

            No basta con comparar contra "*": tanto uvicorn (``_TrustedHosts``,
            uvicorn 0.46) como ``api.middleware._trusted_client_ip`` resuelven
            rangos CIDR, así que ``0.0.0.0/0`` (o ``::/0``) reproduce el agujero
            exacto que este validator existe para cerrar. Un prefijo de longitud
            0 cubre todo el espacio de direcciones de su familia.
            """
            if entrada == "*":
                return True
            try:
                return ipaddress.ip_network(entrada, strict=False).prefixlen == 0
            except ValueError:
                return False

        if not entries or any(_confia_en_todos(entry) for entry in entries):
            raise ValueError(
                "FORWARDED_ALLOW_IPS no puede estar vacío ni contener el comodín '*' "
                "(ni un rango que lo abarque todo, como '0.0.0.0/0' o '::/0') "
                "en ENV=prod/staging con APP_PROFILE=api: con '*' cualquier cliente "
                "puede falsificar su IP vía X-Forwarded-For y con ello se caen el "
                "rate limiting, el lockout de login y la trazabilidad del audit log. "
                "Configura la IP o el rango CIDR del reverse proxy que tenés delante "
                '(ej: FORWARDED_ALLOW_IPS="10.0.0.0/8").'
            )
        return self

    @model_validator(mode="after")
    def _validate_prod_api_hmac_secret(self) -> Settings:
        """En producción, exigir HMAC secret robusto para API keys."""
        if self._is_prod_data and self._serves_http:
            secret = self.API_HMAC_SECRET.get_secret_value()
            if not secret:
                raise ValueError(
                    "API_HMAC_SECRET es obligatorio en ENV=prod con APP_PROFILE=api para hashear API keys con HMAC. "
                    'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
                )
            if len(secret) < 32:
                raise ValueError(
                    "API_HMAC_SECRET demasiado corto. Usa al menos 32 caracteres "
                    "(recomendado: secrets.token_hex(32))."
                )
        return self

    @model_validator(mode="after")
    def _validate_prod_audit_hmac_secret(self) -> Settings:
        """db/audit.py solo lo usa el proceso API (login, exports, acciones admin) —
        el scraper/scheduler nunca llama a log_action/log_event, así que este
        validator debe seguir el mismo gating que sus hermanos (_serves_http).
        Sin esto, el job diario de scraping (APP_PROFILE=scraper) no arranca."""
        if (
            self._is_prod_data
            and self._serves_http
            and len(self.AUDIT_HMAC_KEY.get_secret_value()) < 32
        ):
            raise ValueError("AUDIT_HMAC_KEY (32+ caracteres) es obligatorio en producción")
        return self

    @model_validator(mode="after")
    def _validate_prod_signing_key_strength(self) -> Settings:
        """En producción, exigir SIGNING_KEY con longitud mínima de 32 chars."""
        if self._is_prod_data and self._serves_http:
            key = self.SIGNING_KEY.get_secret_value()
            if key and len(key) < 32:
                raise ValueError(
                    "SIGNING_KEY demasiado corto. Usa al menos 32 caracteres "
                    '(recomendado: python -c "import secrets; print(secrets.token_hex(32))").'
                )
        return self

    @model_validator(mode="after")
    def _validate_prod_password_not_weak(self) -> Settings:
        """En producción, rechazar contraseñas débiles conocidas.

        Aplica a todos los perfiles: cualquier proceso puede exponer Grafana.
        """
        if not self._is_prod_data:
            return self
        from shared.password_policy import check_password_strength

        # Validar GF_SECURITY_ADMIN_PASSWORD
        gf_pw = self.GF_SECURITY_ADMIN_PASSWORD.get_secret_value()
        if gf_pw:
            result = check_password_strength(
                gf_pw,
                min_length=16,
                label="GF_SECURITY_ADMIN_PASSWORD",
            )
            if not result.is_strong:
                raise ValueError(
                    f"GF_SECURITY_ADMIN_PASSWORD es débil: {result.summary}. "
                    "Usa una contraseña de al menos 16 caracteres."
                )
        return self

    @model_validator(mode="after")
    def _validate_prod_smtp_password(self) -> Settings:
        """En producción, exigir SMTP password si hay destinatarios de alertas.

        Aplica a todos los perfiles: el scraper y los workers también notifican.
        """
        if (
            self._is_prod_data
            and self.ALERT_EMAIL_TO
            and not self.ALERT_SMTP_PASSWORD.get_secret_value()
        ):
            raise ValueError(
                "ALERT_SMTP_PASSWORD es obligatorio cuando ALERT_EMAIL_TO está "
                "configurado en ENV=prod. Configura un app password de Gmail."
            )
        return self

    @model_validator(mode="after")
    def _validate_prod_cors_origins(self) -> Settings:
        """En producción, alertar si CORS_ALLOWED_ORIGINS está vacío."""
        if self._is_prod_data and self._serves_http and not self.CORS_ALLOWED_ORIGINS:
            warnings.warn(
                "CORS_ALLOWED_ORIGINS está vacío en ENV=prod. Todas las solicitudes "
                "cross-origin serán bloqueadas. Configura los orígenes permitidos: "
                'CORS_ALLOWED_ORIGINS="https://app.example.com"',
                stacklevel=2,
            )
        return self

    @model_validator(mode="after")
    def _validate_prod_redis(self) -> Settings:
        """En producción, exigir REDIS_URL para cache compartido.

        Solo aplica al perfil ``api``: la caché de respuestas y los rate limits
        viven en el proceso HTTP. El scraper y los workers no la usan.
        """
        if self._is_prod_data and self._serves_http and not self.REDIS_URL:
            raise ValueError(
                "REDIS_URL es obligatorio en ENV=prod/staging con APP_PROFILE=api para cache "
                "compartido entre procesos. Formato: redis://[:password@]host[:port][/db]"
            )
        if (
            self._is_prod_data
            and self._serves_http
            and self.REDIS_URL
            and not self.REDIS_PASSWORD.get_secret_value()
        ):
            raise ValueError(
                "REDIS_PASSWORD es obligatorio en ENV=prod con APP_PROFILE=api. "
                'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return self

    @model_validator(mode="after")
    def _validate_prod_oauth_domains(self) -> Settings:
        """En producción, OAuth sin allowlist es fail-closed: el arranque se rechaza.

        Hasta 2026-08 esto era solo un ``warnings.warn`` — con ambos allowlists
        vacíos, cualquier cuenta de Google podía iniciar sesión en producción y
        el único rastro era una línea de log que nadie mira en el arranque.
        Un producto B2B con datos de clientes no debe poder desplegarse en ese
        estado por accidente; quien de verdad quiera login abierto puede poner
        ``OAUTH_ALLOWED_DOMAINS=*`` de forma explícita y auditable.
        """
        if (
            self._is_prod_data
            and self._serves_http
            and self.GOOGLE_CLIENT_ID
            and not self.OAUTH_ALLOWED_DOMAINS
            and not self.OAUTH_ALLOWED_EMAILS
        ):
            raise ValueError(
                "OAUTH_ALLOWED_DOMAINS y OAUTH_ALLOWED_EMAILS están vacíos con "
                "Google OAuth activo en producción: cualquier cuenta de Google "
                "podría iniciar sesión. Configura al menos uno de los dos; para "
                "permitir cualquier cuenta de forma deliberada, usa "
                "OAUTH_ALLOWED_DOMAINS=*."
            )
        return self

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _validate_database_url_scheme(cls, v: object) -> object:
        """Rechaza esquemas peligrosos en DATABASE_URL.

        Solo se permiten ``postgresql://`` y ``postgres://``. Un valor vacío
        indica que no se usa Postgres (fallback a SQLite local), lo cual es
        válido. El chequeo de ``sslmode`` vive en ``_validate_prod_database_ssl``
        (model_validator) porque depende de ``self.ENV``, no disponible aún
        en un field_validator per-campo.
        """
        value = v.get_secret_value() if isinstance(v, SecretStr) else v
        if not isinstance(value, str) or not value:
            return v
        allowed = ("postgresql://", "postgres://")
        if not value.startswith(allowed):
            raise ValueError(
                f"DATABASE_URL tiene un esquema no permitido. "
                f"Se esperaba uno de {allowed}, se recibió un valor que no matchea."
            )
        return v

    @model_validator(mode="after")
    def _validate_prod_database_ssl(self) -> Settings:
        """Exigir TLS verificado en DATABASE_URL (Postgres/Supabase) cuando aplica.

        ``sslmode=require`` cifra pero NO valida el certificado ni el hostname del
        servidor: un atacante capaz de interponerse (MITM) puede presentar su
        propio certificado y capturar credenciales + datos. ``verify-full`` valida
        cadena + hostname (necesita ``DATABASE_SSL_ROOT_CERT`` = CA de Supabase).

        La política se aplica (``enforce``) si ``ENV`` es prod/staging **o** si el
        host es remoto (no localhost/127.0.0.1/::1) — independientemente de ENV.
        F4 (2026-07-13): esto cierra el gap de ``scrape-daily.yml``, que corre con
        ``ENV=dev`` pero apunta a Supabase real — antes esa combinación solo
        avisaba, nunca bloqueaba una conexión sin TLS verificado. Un host local
        (docker-compose/desarrollo con Postgres en la propia máquina) no tiene red
        externa que interceptar, así que ahí sigue bastando con avisar.

        Política cuando ``enforce``:
          - ``sslmode`` ausente → error (psycopg podría negociar sin TLS).
          - ``disable``/``allow``/``prefer`` → error (no garantizan TLS; cierran el
            downgrade silencioso que el chequeo por substring anterior permitía).
          - ``require``/``verify-ca`` → permitido con warning (se recomienda verify-full).
          - ``verify-full`` → OK.
        Si no aplica (dev + host local), solo se avisa.
        """
        url = self.DATABASE_URL.get_secret_value()
        if not url:
            return self

        host = _extract_host(url)
        is_prod = self.ENV in ("prod", "staging")
        is_remote = host not in _LOCAL_DB_HOSTS
        enforce = is_prod or is_remote
        sslmode = _extract_sslmode(url)

        if sslmode is None:
            if enforce:
                reason = (
                    "en ENV=prod/staging"
                    if is_prod
                    else f"apuntando a un host remoto ({host}), sea cual sea ENV"
                )
                raise ValueError(
                    f"DATABASE_URL no especifica sslmode {reason}. Añade "
                    "'?sslmode=verify-full' (con DATABASE_SSL_ROOT_CERT) para exigir "
                    "TLS verificado en la conexión a Postgres/Supabase."
                )
            warnings.warn(
                "DATABASE_URL no especifica sslmode. Añade '?sslmode=verify-full' "
                "para exigir TLS verificado en la conexión a Postgres/Supabase.",
                stacklevel=2,
            )
            return self

        insecure = {"disable", "allow", "prefer"}
        if sslmode in insecure:
            if enforce:
                reason = (
                    "en ENV=prod/staging"
                    if is_prod
                    else f"apuntando a un host remoto ({host}), sea cual sea ENV"
                )
                raise ValueError(
                    f"DATABASE_URL usa sslmode={sslmode!r}, que no garantiza TLS, {reason}. "
                    "Usa 'verify-full' (recomendado) o al menos 'require'."
                )
            warnings.warn(
                f"DATABASE_URL usa sslmode={sslmode!r}, que puede conectar sin TLS. "
                "Usa 'verify-full' para exigir TLS verificado.",
                stacklevel=2,
            )
            return self

        if enforce and sslmode in ("require", "verify-ca"):
            warnings.warn(
                f"DATABASE_URL usa sslmode={sslmode!r}: cifra pero no valida "
                "completamente el certificado del servidor. Se recomienda "
                "'verify-full' con DATABASE_SSL_ROOT_CERT (CA de Supabase) para "
                "prevenir ataques MITM.",
                stacklevel=2,
            )
        return self


def _load() -> Settings:
    return Settings()


_settings = _load()

# ── Singleton accesible para nuevos consumidores ─────────────────────────
# Uso recomendado: ``from config import settings`` y luego ``settings.DB_PATH``.
settings = _settings


def ensure_data_dirs() -> None:
    """Crea los directorios de datos si no existen."""
    _settings.DATA_DIR.mkdir(exist_ok=True)
    downloads = _settings.DOWNLOADS_DIR
    if downloads is not None:
        downloads.mkdir(exist_ok=True)
