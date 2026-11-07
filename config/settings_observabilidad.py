"""Settings de observabilidad: trazas, logs, latido del healthcheck, Grafana y anomalías.

Módulo hermano de ``config/settings.py`` (P3 «Los dos módulos-dios»): ``Settings``
hereda de esta clase, así que los nombres de las variables de entorno y el
acceso (``settings.OTEL_SERVICE_NAME``) son los de siempre.

Sin ``model_config`` propio, por lo mismo que ``config/settings_resumen.py``.
"""

from __future__ import annotations

from typing import Self

from pydantic import SecretStr, field_validator, model_validator

from config.settings_entorno import EntornoSettings


class ObservabilidadSettings(EntornoSettings):
    """OpenTelemetry, formato de log, nivel de alerta, heartbeat, Grafana y anomalías."""

    # ── OpenTelemetry ─────────────────────────────────────────────────────
    # Si está vacío, el tracing opera en modo NoOp (sin overhead)
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = "tenderflow"
    # Fracción de trazas a muestrear [0.0-1.0]. Las trazas con error se
    # muestrean siempre independientemente de este valor.
    # Default 0.1 (10%) — suficiente para debugging en un sistema de scraping
    # con volumen moderado. Ajustar a 0.01 en entornos de alto tráfico.
    OTEL_SAMPLE_RATIO: float = 0.1

    # ── Observabilidad ───────────────────────────────────────────────────
    LOG_FORMAT: str = ""
    ALERT_MIN_LEVEL: str = "warn"
    # Dead-man's switch del healthcheck (scheduler/latido.py): URL que un
    # servicio externo espera recibir tras cada chequeo con alertas. Vacía →
    # no se hace ninguna petición. Es SecretStr porque quien la conoce puede
    # fingir el latido.
    HEALTHCHECK_HEARTBEAT_URL: SecretStr = SecretStr("")

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

    @field_validator("OTEL_SAMPLE_RATIO", mode="before")
    @classmethod
    def _validate_otel_sample_ratio(cls, v: object) -> float:
        val = float(v)  # type: ignore[arg-type]  # mode="before": v llega crudo y float() es la comprobación
        if not (0.0 <= val <= 1.0):
            raise ValueError("OTEL_SAMPLE_RATIO debe estar entre 0.0 y 1.0")
        return val

    @model_validator(mode="after")
    def _validate_prod_password_not_weak(self) -> Self:
        """En producción, rechazar contraseñas débiles conocidas.

        Aplica a todos los perfiles: cualquier proceso puede exponer Grafana.
        """
        if not self._is_prod_data:
            return self
        from config.password_policy import check_password_strength

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
