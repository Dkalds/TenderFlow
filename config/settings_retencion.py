"""Settings de retención de datos (C9.3): plazos de purga por tabla.

Módulo hermano de ``config/settings.py`` (P3 «Los dos módulos-dios»): ``Settings``
hereda de esta clase, así que los nombres de las variables de entorno y el
acceso (``settings.RETENTION_AUDIT_LOG_DAYS``) son los de siempre.

Sin ``model_config`` propio, por lo mismo que ``config/settings_resumen.py``.
"""

from __future__ import annotations

from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings


class RetencionSettings(BaseSettings):
    """Plazos que aplica ``scheduler/retention.py::POLITICA_RETENCION``."""

    # ── Retención de datos (C9.3) ──────────────────────────────────
    # Hasta 2026-09 estos plazos vivían como literales en los argumentos por
    # defecto de `scheduler/retention.py::run_retention` y en los `--*-days` de
    # `scripts/retention_cleanup.py`. Consecuencia: no había un sitio donde
    # leerlos, no aparecían en `docs/SECURITY.md`, y el job programado y el CLI
    # podían divergir sin que nada fallara.
    #
    # Ahora son configuración, la política se declara en
    # `scheduler/retention.py::POLITICA_RETENCION` (tabla, motivo y comando) y
    # `scripts/gen_retention_doc.py` publica la tabla. `0` desactiva la purga de
    # esa tabla; un negativo no tiene sentido y el validador lo rechaza.
    RETENTION_EXTRACTION_RUNS_DAYS: int = 90
    RETENTION_AUDIT_LOG_DAYS: int = 180
    RETENTION_DLQ_DAYS: int = 30
    RETENTION_LICITACIONES_HISTORY_DAYS: int = 365
    RETENTION_ACCESS_LOG_DAYS: int = 180
    RETENTION_IDEMPOTENCY_KEYS_DAYS: int = 1
    RETENTION_WEBHOOK_DELIVERIES_DAYS: int = 90
    # Publicado en el aviso legal (`web/src/lib/legal.ts`). Cambiarlo cambia una
    # promesa hecha al visitante: `tests/test_retention_solicitudes.py` exige que
    # los dos números coincidan.
    RETENTION_SOLICITUDES_ACCESO_MESES: int = 24
    RETENTION_PASSWORD_RESET_DAYS: int = 7
    # Altas con contraseña que nadie verificó (RFC 2026-10-21): cuentas sin uso
    # con el correo de una persona. El enlace caduca en 24 horas.
    RETENTION_UNVERIFIED_SIGNUP_DAYS: int = 7
    # Errores de cliente (C2.6): huella sin PII, no hace falta conservarla más
    # de lo que dura investigar una regresión.
    RETENTION_CLIENT_ERRORS_DAYS: int = 30
    # Feedback del asistente (C5.4): sin texto libre salvo opt-in explícito.
    RETENTION_ASISTENTE_FEEDBACK_DAYS: int = 365
    # Invitaciones a una organización: guardan el correo de quien aún puede no
    # tener cuenta. Se purgan pasados estos días desde que caducaron, aceptadas o no.
    RETENTION_ORG_INVITATIONS_DAYS: int = 90
    # Outbox de eventos (ADR-027): solo los ya despachados. El payload de un
    # evento puede nombrar a la persona que lo originó (`pursuit.assigned`).
    RETENTION_DOMAIN_EVENTS_DAYS: int = 365

    @model_validator(mode="after")
    def _validate_retention_days(self) -> Self:
        """Un plazo de retención negativo borraría el futuro: se rechaza al arrancar.

        `0` sí es válido y significa «no purgar esta tabla», que es una decisión
        operativa legítima. Lo que no puede pasar es que un typo en una variable
        de entorno convierta la purga en un `DELETE` sin cota inferior.
        """
        negativos = [
            nombre
            for nombre in type(self).model_fields
            if nombre.startswith("RETENTION_") and int(getattr(self, nombre)) < 0
        ]
        if negativos:
            raise ValueError(f"plazos de retención negativos: {', '.join(sorted(negativos))}")
        return self
