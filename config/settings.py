"""Configuración global del proyecto — basada en pydantic-settings."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent

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
    ENV: Literal["dev", "staging", "prod"] = "prod"

    # ── Rutas ────────────────────────────────────────────────────────────
    DATA_DIR: Path = _DEFAULT_DATA_DIR
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

    # ── Modelos predictivos (Fase 6, RFC 20260611-2) ─────────────────────
    # Si True, el re-entrenamiento mensual activa la versión nueva
    # automáticamente cuando bate todas las métricas vs la activa (criterios
    # del RFC). Por defecto la activación es manual (model_registry).
    ML_PRED_AUTO_ACTIVATE: bool = False

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
    OTEL_SERVICE_NAME: str = "licitaciones-sap"
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

    SIGNING_KEY: SecretStr = SecretStr("")

    # Clave maestra para derivar secretos de webhook (HMAC-SHA256).
    # Si vacío, se deriva de SIGNING_KEY como fallback.
    # Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"
    WEBHOOK_SIGNING_KEY: SecretStr = SecretStr("")

    # Clave Fernet para cifrar secretos TOTP at-rest. Obligatoria en prod.
    # Genera una con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    TOTP_ENCRYPTION_KEY: SecretStr = SecretStr("")

    # ── Turso ────────────────────────────────────────────────────────────
    TURSO_DATABASE_URL: str = ""
    TURSO_AUTH_TOKEN: SecretStr = SecretStr("")
    TURSO_LOCAL_DB: Path | None = None
    # URL de la réplica de lectura Turso (opcional). Si se configura, las
    # consultas SELECT se enrutan a la réplica para reducir latencia.
    TURSO_REPLICA_URL: str = ""

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
    DB_POOL_TIMEOUT: float = 10.0

    # ── Scraper ──────────────────────────────────────────────────────────
    REQUEST_TIMEOUT: int = 30
    REQUEST_DELAY_SECONDS: float = 1.5
    MAX_DOWNLOAD_SIZE_BYTES: int = 200 * 1024 * 1024
    MAX_XML_SIZE_BYTES: int = 150 * 1024 * 1024
    DAILY_MAX_PAGES: int = 50
    BACKFILL_MAX_WORKERS: int = 3

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
    # Versión lógica del índice FAISS — si cambia, se regenera el índice
    EMBEDDING_VERSION: str = "v1"

    # ── Scoring de oportunidades ─────────────────────────────────────────
    # Pesos por dimensión (enteros, deben sumar 100 cuando afinidad está activa).
    # Overridable via ENV como JSON:
    #   SCORING_WEIGHTS='{"importe":25,"plazo":15,"competencia":25,"margen":20,"afinidad":15}'
    SCORING_WEIGHTS: dict[str, int] = {
        "importe": 25,
        "plazo": 15,
        "competencia": 25,
        "margen": 20,
        "afinidad": 15,
    }
    # Keywords de afinidad configurables por el usuario (casefold-substring sobre título).
    # Si está vacía, la dimensión afinidad se omite del desglose y su peso se
    # redistribuye proporcionalmente entre las demás dimensiones.
    # Overridable via ENV como JSON:
    #   SCORING_AFINIDAD_KEYWORDS='["consultoría","mantenimiento"]'
    SCORING_AFINIDAD_KEYWORDS: list[str] = []

    # ── API REST ─────────────────────────────────────────────────────────
    # IPs (o rangos) que pueden acceder a /metrics sin API key (separadas por coma).
    # Por defecto solo loopback. En producción añadir la IP del servidor Prometheus.
    # Ej: "127.0.0.1,10.0.0.5,10.0.0.6"
    METRICS_ALLOWED_IPS: str = "127.0.0.1"

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

    # ── Cola de tareas (Dramatiq, opcional) ──────────────────────────────
    # Si se deja vacío se usa StubBroker (ejecución síncrona, para dev/tests).
    DRAMATIQ_BROKER_URL: str = ""

    # Modo de cola explícito: "auto" (default) detecta dramatiq/redis automáticamente.
    # En producción, se recomienda setear "dramatiq" para fail-fast si falta Redis.
    # Valores: "auto" | "dramatiq" | "inline"
    QUEUE_MODE: str = "auto"

    # ── Validators ───────────────────────────────────────────────────────

    @model_validator(mode="after")
    def _validate_scoring_weights(self) -> Settings:
        weights = self.SCORING_WEIGHTS
        allowed_keys = {"importe", "plazo", "competencia", "margen", "afinidad"}
        for key, val in weights.items():
            if key not in allowed_keys:
                raise ValueError(
                    f"SCORING_WEIGHTS contiene clave desconocida: {key!r}. "
                    f"Claves permitidas: {sorted(allowed_keys)}"
                )
            if val < 0:
                raise ValueError(
                    f"SCORING_WEIGHTS[{key!r}] = {val} es negativo. Todos los pesos deben ser >= 0."
                )
        total = sum(weights.values())
        if total != 100:
            raise ValueError(
                f"SCORING_WEIGHTS suma {total}, debe ser exactamente 100. "
                f"Valores actuales: {weights}"
            )
        afinidad = weights.get("afinidad", 0)
        if afinidad >= 100:
            raise ValueError(f"SCORING_WEIGHTS['afinidad'] = {afinidad} debe ser < 100.")
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
        if self.TURSO_LOCAL_DB is None:
            self.TURSO_LOCAL_DB = self.DATA_DIR / "licitaciones_replica.db"
        return self

    @model_validator(mode="after")
    def _validate_turso_pair(self) -> Settings:
        url = self.TURSO_DATABASE_URL
        token = self.TURSO_AUTH_TOKEN.get_secret_value()
        if bool(url) ^ bool(token):
            warnings.warn(
                "Configuración Turso incompleta: se necesitan TURSO_DATABASE_URL y "
                "TURSO_AUTH_TOKEN juntas. Se usará SQLite local como fallback.",
                stacklevel=2,
            )
            self.TURSO_DATABASE_URL = ""
            self.TURSO_AUTH_TOKEN = SecretStr("")
        return self

    @model_validator(mode="after")
    def _validate_prod_signing_key(self) -> Settings:
        if self.ENV in ("prod", "staging") and not self.SIGNING_KEY.get_secret_value():
            raise ValueError(
                "SIGNING_KEY es obligatorio en ENV=prod para firmar tokens CSRF/OAuth. "
                'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return self

    @model_validator(mode="after")
    def _validate_prod_webhook_signing_key(self) -> Settings:
        """En producción, exigir WEBHOOK_SIGNING_KEY o SIGNING_KEY como fallback."""
        if self.ENV in ("prod", "staging"):
            wk = self.WEBHOOK_SIGNING_KEY.get_secret_value()
            sk = self.SIGNING_KEY.get_secret_value()
            if not wk and not sk:
                raise ValueError(
                    "WEBHOOK_SIGNING_KEY (o SIGNING_KEY como fallback) es obligatorio "
                    "en ENV=prod para derivar secretos de webhook. "
                    'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
                )
        return self

    @model_validator(mode="after")
    def _validate_prod_api_hmac_secret(self) -> Settings:
        """En producción, exigir HMAC secret robusto para API keys."""
        if self.ENV in ("prod", "staging"):
            secret = self.API_HMAC_SECRET.get_secret_value()
            if not secret:
                raise ValueError(
                    "API_HMAC_SECRET es obligatorio en ENV=prod para hashear API keys con HMAC. "
                    'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
                )
            if len(secret) < 32:
                raise ValueError(
                    "API_HMAC_SECRET demasiado corto. Usa al menos 32 caracteres "
                    "(recomendado: secrets.token_hex(32))."
                )
        return self

    @model_validator(mode="after")
    def _validate_prod_signing_key_strength(self) -> Settings:
        """En producción, exigir SIGNING_KEY con longitud mínima de 32 chars."""
        if self.ENV in ("prod", "staging"):
            key = self.SIGNING_KEY.get_secret_value()
            if key and len(key) < 32:
                raise ValueError(
                    "SIGNING_KEY demasiado corto. Usa al menos 32 caracteres "
                    '(recomendado: python -c "import secrets; print(secrets.token_hex(32))").'
                )
        return self

    @model_validator(mode="after")
    def _validate_prod_password_not_weak(self) -> Settings:
        """En producción, rechazar contraseñas débiles conocidas."""
        if self.ENV not in ("prod", "staging"):
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
        """En producción, exigir SMTP password si hay destinatarios de alertas."""
        if (
            self.ENV in ("prod", "staging")
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
        if self.ENV in ("prod", "staging") and not self.CORS_ALLOWED_ORIGINS:
            warnings.warn(
                "CORS_ALLOWED_ORIGINS está vacío en ENV=prod. Todas las solicitudes "
                "cross-origin serán bloqueadas. Configura los orígenes permitidos: "
                'CORS_ALLOWED_ORIGINS="https://app.example.com"',
                stacklevel=2,
            )
        return self

    @model_validator(mode="after")
    def _validate_prod_redis(self) -> Settings:
        """En producción, exigir REDIS_URL para cache compartido."""
        if self.ENV in ("prod", "staging") and not self.REDIS_URL:
            raise ValueError(
                "REDIS_URL es obligatorio en ENV=prod/staging para cache compartido entre "
                "procesos. Formato: redis://[:password@]host[:port][/db]"
            )
        if (
            self.ENV in ("prod", "staging")
            and self.REDIS_URL
            and not self.REDIS_PASSWORD.get_secret_value()
        ):
            raise ValueError(
                "REDIS_PASSWORD es obligatorio en ENV=prod. "
                'Genera uno con: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return self

    @model_validator(mode="after")
    def _validate_prod_oauth_domains(self) -> Settings:
        """En producción, alertar si no hay restricción de dominios/emails OAuth."""
        if (
            self.ENV in ("prod", "staging")
            and self.GOOGLE_CLIENT_ID
            and not self.OAUTH_ALLOWED_DOMAINS
            and not self.OAUTH_ALLOWED_EMAILS
        ):
            warnings.warn(
                "OAUTH_ALLOWED_DOMAINS y OAUTH_ALLOWED_EMAILS están vacíos con "
                "OAuth habilitado en ENV=prod. Cualquier cuenta Google podrá acceder. "
                "Configura al menos uno de ellos para restringir el acceso.",
                stacklevel=2,
            )
        return self

    @field_validator("TURSO_DATABASE_URL", mode="before")
    @classmethod
    def _validate_turso_url_scheme(cls, v: object) -> object:
        """Rechaza esquemas peligrosos en TURSO_DATABASE_URL.

        Solo se permiten ``libsql://`` y ``https://`` (embedded replica).
        Un valor vacío indica que no se usa Turso, lo cual es válido.
        """
        if not isinstance(v, str) or not v:
            return v
        allowed = ("libsql://", "https://")
        if not v.startswith(allowed):
            raise ValueError(
                f"TURSO_DATABASE_URL tiene un esquema no permitido. "
                f"Se esperaba uno de {allowed}, se recibió: {v!r}"
            )
        return v


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
