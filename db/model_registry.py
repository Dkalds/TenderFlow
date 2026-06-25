"""Model registry for ML lifecycle (C2).

Persiste metadata de versiones de modelos entrenados en la tabla
``model_versions``. Permite:

* Registrar nuevas versiones (al re-entrenar)
* Marcar la versión activa (la que usan los predictores)
* Listar histórico para A/B testing y auditoría
* Revertir a versiones previas si una nueva degrada métricas

Ejemplo::

    from db.model_registry import register_version, get_active

    register_version(
        name="sap_classifier",
        path="data/models/sap_classifier_v3.pkl",
        sha256="abc...",
        metrics={"accuracy": 0.92, "f1": 0.88},
        n_samples=1500,
        n_feedbacks=120,
        activate=True,
    )

    active = get_active("sap_classifier")  # → dict con path, version, etc.
"""

from __future__ import annotations

import json
from typing import Any

from db.database import connect, now_utc_iso
from observability.logging import get_logger

log = get_logger(__name__)


def register_version(
    *,
    name: str,
    path: str,
    sha256: str,
    metrics: dict[str, Any] | None = None,
    n_samples: int | None = None,
    n_feedbacks: int | None = None,
    notes: str | None = None,
    activate: bool = False,
) -> int:
    """Registra una nueva versión del modelo.

    Si ``activate=True``, desactiva las anteriores y deja esta como is_active=1.
    Devuelve el ``version`` asignado (auto-incremento por ``name``).
    """
    with connect() as c:
        row = c.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM model_versions WHERE name = ?",
            (name,),
        ).fetchone()
        next_version = int(row[0])

        c.execute(
            "INSERT INTO model_versions "
            "(name, version, path, sha256, metrics_json, trained_at, "
            " trained_on_n_samples, trained_on_n_feedbacks, is_active, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                next_version,
                path,
                sha256,
                json.dumps(metrics or {}, ensure_ascii=False),
                now_utc_iso(),
                n_samples,
                n_feedbacks,
                1 if activate else 0,
                notes,
            ),
        )

        if activate:
            c.execute(
                "UPDATE model_versions SET is_active = 0 WHERE name = ? AND version != ?",
                (name, next_version),
            )

    log.info(
        "model_registered",
        name=name,
        version=next_version,
        active=activate,
        n_samples=n_samples,
        n_feedbacks=n_feedbacks,
    )
    return next_version


def get_active(name: str) -> dict[str, Any] | None:
    """Devuelve la versión activa del modelo ``name`` o None si no hay."""
    with connect() as c:
        cur = c.execute(
            "SELECT id, name, version, path, sha256, metrics_json, trained_at, "
            "trained_on_n_samples, trained_on_n_feedbacks, is_active, notes "
            "FROM model_versions WHERE name = ? AND is_active = 1 "
            "ORDER BY version DESC LIMIT 1",
            (name,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
    data = dict(zip(cols, row, strict=False))
    data["metrics"] = json.loads(data.pop("metrics_json", "{}") or "{}")
    return data


def list_versions(name: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Lista las últimas ``limit`` versiones del modelo ``name``."""
    with connect() as c:
        cur = c.execute(
            "SELECT id, name, version, path, sha256, metrics_json, trained_at, "
            "trained_on_n_samples, trained_on_n_feedbacks, is_active, notes "
            "FROM model_versions WHERE name = ? "
            "ORDER BY version DESC LIMIT ?",
            (name, limit),
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(zip(cols, row, strict=False))
        d["metrics"] = json.loads(d.pop("metrics_json", "{}") or "{}")
        out.append(d)
    return out


def activate_version(name: str, version: int) -> bool:
    """Activa la versión ``version`` del modelo ``name`` (rollback / A/B switch).

    Devuelve True si la versión existía y se activó.
    """
    with connect() as c:
        cur = c.execute(
            "SELECT 1 FROM model_versions WHERE name = ? AND version = ?",
            (name, version),
        )
        if not cur.fetchone():
            return False
        c.execute(
            "UPDATE model_versions SET is_active = "
            "CASE WHEN version = ? THEN 1 ELSE 0 END WHERE name = ?",
            (version, name),
        )
    log.info("model_activated", name=name, version=version)
    return True


def active_model_summary(name: str = "sap_classifier") -> dict[str, Any]:
    """Resumen del modelo activo para el panel de active learning.

    Compone la versión activa, las etiquetas acumuladas desde su entrenamiento y
    el histórico reciente de métricas (para ver la tendencia). Todo desde la BD;
    **no carga el modelo ML**, así que es barato y seguro de exponer. Cierra el
    bucle: el etiquetado deja de sentirse gratis porque se ve su impacto.
    """
    active = get_active(name)
    history = [
        {"version": h["version"], "trained_at": h["trained_at"], "metrics": h["metrics"]}
        for h in list_versions(name, limit=10)
    ]
    return {
        "name": name,
        "active": active,
        "feedbacks_since_train": feedbacks_since_last_train(name),
        "history": history,
    }


def feedbacks_since_last_train(name: str = "sap_classifier") -> int:
    """Cuenta filas en ``ml_feedback`` desde el ``trained_at`` de la versión activa.

    Si no hay versión activa, devuelve el total. Usado por C1 (active learning).
    """
    active = get_active(name)
    with connect() as c:
        if active is None:
            cur = c.execute("SELECT COUNT(*) FROM ml_feedback")
        else:
            cur = c.execute(
                "SELECT COUNT(*) FROM ml_feedback WHERE created_at > ?",
                (active["trained_at"],),
            )
        row = cur.fetchone()
    return int(row[0]) if row else 0
