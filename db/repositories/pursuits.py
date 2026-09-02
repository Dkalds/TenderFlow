"""Persistencia transaccional de pursuits y su ledger append-only."""

from __future__ import annotations

import json
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts

_PURSUIT_SELECT = (
    "SELECT p.id, p.organization_id, p.licitacion_id, "
    "l.titulo AS tender_title, l.fecha_limite AS tender_deadline, "
    "p.responsible_user_id, u.display_name AS responsible_name, "
    "p.status, p.decision, p.decision_reason, p.offer_price_eur, "
    "p.outcome, p.awarded_amount_eur, p.outcome_reason, "
    "p.next_action, p.next_action_due, "
    "p.identified_at, p.decision_at, p.submitted_at, p.closed_at, "
    "p.created_at, p.updated_at, p.version, "
    # Contador del hilo de comentarios en la misma consulta: el tablero lo
    # pinta en cada tarjeta y una llamada por oportunidad no escala (v97).
    "(SELECT COUNT(*) FROM pursuit_comments c WHERE c.pursuit_id = p.id) AS comments_count "
    "FROM pursuits p "
    "JOIN licitaciones l ON l.id_externo = p.licitacion_id "
    "LEFT JOIN users u ON u.id = p.responsible_user_id "
)

_UPDATABLE_COLUMNS = frozenset(
    {
        "responsible_user_id",
        "status",
        "decision",
        "decision_reason",
        "offer_price_eur",
        "outcome",
        "awarded_amount_eur",
        "outcome_reason",
        "next_action",
        "next_action_due",
        "decision_at",
        "submitted_at",
        "closed_at",
    }
)

# Estados que sacan un pursuit de la agenda: ya no hay trabajo pendiente.
_ESTADOS_TERMINALES_SQL = "('won', 'lost', 'withdrawn')"

_AGENDA_SELECT = (
    "SELECT p.id AS pursuit_id, p.licitacion_id, "
    "l.titulo, l.fecha_limite AS tender_deadline, l.importe AS importe_eur, "
    "l.organo_contratacion AS organo, l.ccaa, l.tecnologia, l.url, "
    "p.responsible_user_id, u.display_name AS responsible_name, "
    "p.status, p.decision, p.next_action, p.next_action_due, p.version "
    "FROM pursuits p "
    "JOIN licitaciones l ON l.id_externo = p.licitacion_id "
    "LEFT JOIN users u ON u.id = p.responsible_user_id "
)


class PursuitConcurrencyError(RuntimeError):
    """La versión cambió entre lectura y escritura."""


class PursuitRepository:
    """Queries de pursuits siempre limitadas por ``organization_id``."""

    def licitacion_exists(self, licitacion_id: str) -> bool:
        with connect_read() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM licitaciones WHERE id_externo = %s",
                    (licitacion_id,),
                ).fetchone()
                is not None
            )

    def create(
        self,
        *,
        organization_id: int,
        licitacion_id: str,
        responsible_user_id: int | None,
        actor_user_id: int,
        idempotency_key: str | None = None,
        score_al_abrir: int | None = None,
        banda_al_abrir: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Crea idempotentemente y registra exactamente un evento inicial.

        ``score_al_abrir``/``banda_al_abrir`` sellan la puntuación que motivó la
        decisión (revisión ``v93``). Sólo se escriben en el INSERT: si el pursuit
        ya existía, se conservan los de la primera vez, que es cuando alguien
        decidió de verdad — reescribirlos en el camino idempotente falsearía la
        medida con el score de un momento en que nadie decidió nada.
        """
        now = now_utc_iso()
        with connect() as conn:
            existing = self._get_scoped(conn, organization_id, licitacion_id=licitacion_id)
            if existing is not None:
                return existing, False

            inserted = conn.execute(
                "INSERT INTO pursuits "
                "(organization_id, licitacion_id, responsible_user_id, "
                " identified_at, created_by_user_id, updated_by_user_id, "
                " created_at, updated_at, score_al_abrir, banda_al_abrir) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT(organization_id, licitacion_id) DO NOTHING RETURNING id",
                (
                    organization_id,
                    licitacion_id,
                    responsible_user_id,
                    now,
                    actor_user_id,
                    actor_user_id,
                    now,
                    now,
                    score_al_abrir,
                    banda_al_abrir,
                ),
            ).fetchone()
            was_created = inserted is not None

            pursuit = self._get_scoped(conn, organization_id, licitacion_id=licitacion_id)
            if pursuit is None:
                raise RuntimeError("No se pudo crear la oportunidad.")
            if was_created:
                self._append_event(
                    conn,
                    pursuit_id=int(pursuit["id"]),
                    organization_id=organization_id,
                    event_type="pursuit.created",
                    actor_user_id=actor_user_id,
                    payload={
                        "licitacion_id": licitacion_id,
                        "responsible_user_id": responsible_user_id,
                        "status": "identified",
                    },
                    idempotency_key=idempotency_key,
                    created_at=now,
                )
            return pursuit, was_created

    def get(self, organization_id: int, pursuit_id: int) -> dict[str, Any] | None:
        with connect_read() as conn:
            return self._get_scoped(conn, organization_id, pursuit_id=pursuit_id)

    def list_scoped(
        self,
        organization_id: int,
        *,
        status: str | None = None,
        responsible_user_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses = ["p.organization_id = %s"]
        params: list[Any] = [organization_id]
        if status is not None:
            clauses.append("p.status = %s")
            params.append(status)
        if responsible_user_id is not None:
            clauses.append("p.responsible_user_id = %s")
            params.append(responsible_user_id)
        where = " AND ".join(clauses)
        with connect_read() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) FROM pursuits p WHERE " + where,
                tuple(params),
            ).fetchone()
            cur = conn.execute(
                _PURSUIT_SELECT
                + " WHERE "
                + where
                + " ORDER BY p.updated_at DESC, p.id DESC LIMIT %s OFFSET %s",
                tuple([*params, limit, offset]),
            )
            items = rows_to_dicts(cur)
        return items, int(total_row[0] if total_row else 0)

    def agenda_rows(
        self,
        organization_id: int,
        *,
        responsible_user_id: int | None = None,
        tecnologia: str | None = None,
        ccaa: str | None = None,
        limit: int = 500,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Pursuits abiertos de la organización con su licitación, para la agenda.

        Devuelve ``(filas, truncado)``: se pide ``limit + 1`` y se recorta, para
        que el servicio pueda declarar el truncamiento en vez de presentar KPIs
        silenciosamente bajos (ADR-014).
        """
        clauses = [
            "p.organization_id = %s",
            "p.status NOT IN " + _ESTADOS_TERMINALES_SQL,
        ]
        params: list[Any] = [organization_id]
        if responsible_user_id is not None:
            clauses.append("p.responsible_user_id = %s")
            params.append(responsible_user_id)
        if tecnologia:
            clauses.append("l.tecnologia = %s")
            params.append(tecnologia)
        if ccaa:
            clauses.append("l.ccaa = %s")
            params.append(ccaa)
        with connect_read() as conn:
            cur = conn.execute(
                _AGENDA_SELECT + " WHERE " + " AND ".join(clauses) + " ORDER BY p.id LIMIT %s",
                tuple([*params, limit + 1]),
            )
            rows = rows_to_dicts(cur)
        return rows[:limit], len(rows) > limit

    def licitacion_ids(self, organization_id: int) -> set[str]:
        """Licitaciones con pursuit (en cualquier estado) en la organización.

        Un pursuit cerrado también cuenta como triado: la señal no debe
        reaparecer en la agenda por haberse perdido o retirado la oportunidad.
        """
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT licitacion_id FROM pursuits WHERE organization_id = %s",
                (organization_id,),
            )
            return {str(row[0]) for row in cur.fetchall()}

    def update(
        self,
        *,
        organization_id: int,
        pursuit_id: int,
        actor_user_id: int,
        changes: dict[str, Any],
        expected_version: int,
        event_payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        """Actualiza y añade el evento en la misma transacción."""
        invalid = set(changes) - _UPDATABLE_COLUMNS
        if invalid:
            raise ValueError(f"Columnas de pursuit no permitidas: {sorted(invalid)}")
        now = now_utc_iso()
        with connect() as conn:
            current = self._get_scoped(conn, organization_id, pursuit_id=pursuit_id)
            if current is None:
                return None
            if idempotency_key and self._event_key_exists(conn, pursuit_id, idempotency_key):
                return current
            if int(current["version"]) != expected_version:
                raise PursuitConcurrencyError("La oportunidad fue modificada por otra persona.")
            if not changes:
                return current

            assignments = [f"{column} = %s" for column in changes]
            values = list(changes.values())
            assignments.extend(
                ["updated_by_user_id = %s", "updated_at = %s", "version = version + 1"]
            )
            values.extend([actor_user_id, now, organization_id, pursuit_id, expected_version])
            sql = (
                "UPDATE pursuits SET "
                + ", ".join(assignments)
                + " WHERE organization_id = %s AND id = %s AND version = %s"
            )
            updated = conn.execute(sql + " RETURNING id", tuple(values)).fetchone()
            did_update = updated is not None
            if not did_update:
                raise PursuitConcurrencyError("La oportunidad fue modificada por otra persona.")
            self._append_event(
                conn,
                pursuit_id=pursuit_id,
                organization_id=organization_id,
                event_type="pursuit.updated",
                actor_user_id=actor_user_id,
                payload=event_payload,
                idempotency_key=idempotency_key,
                created_at=now,
            )
            return self._get_scoped(conn, organization_id, pursuit_id=pursuit_id)

    def list_events(self, organization_id: int, pursuit_id: int) -> list[dict[str, Any]]:
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT id, pursuit_id, event_type, actor_user_id, payload_json, created_at "
                "FROM pursuit_events WHERE organization_id = %s AND pursuit_id = %s "
                "ORDER BY id",
                (organization_id, pursuit_id),
            )
            events = rows_to_dicts(cur)
        for event in events:
            try:
                event["payload"] = json.loads(str(event.pop("payload_json")))
            except (TypeError, json.JSONDecodeError):
                event["payload"] = {}
        return events

    def metric_rows(
        self,
        organization_id: int,
        *,
        period_from: str | None = None,
        period_to: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["organization_id = %s"]
        params: list[Any] = [organization_id]
        if period_from is not None:
            clauses.append("identified_at >= %s")
            params.append(period_from)
        if period_to is not None:
            clauses.append("identified_at < %s")
            params.append(period_to)
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT status, outcome, awarded_amount_eur, identified_at, "
                "decision_at, submitted_at FROM pursuits WHERE " + " AND ".join(clauses),
                tuple(params),
            )
            return rows_to_dicts(cur)

    def export_personal_data(self, user_id: int) -> dict[str, list[dict[str, Any]]]:
        """Exporta solo filas vinculadas personalmente al usuario.

        Cada resultado se materializa antes de lanzar la siguiente query: la
        conexión expone un único cursor y ``execute`` lo reemplaza, así que dos
        cursores "vivos" a la vez apuntan al mismo resultado (el último).
        """
        with connect_read() as conn:
            pursuits = rows_to_dicts(
                conn.execute(
                    "SELECT * FROM pursuits WHERE responsible_user_id = %s "
                    "OR created_by_user_id = %s OR updated_by_user_id = %s "
                    "ORDER BY id LIMIT 5000",
                    (user_id, user_id, user_id),
                )
            )
            events = rows_to_dicts(
                conn.execute(
                    "SELECT id, pursuit_id, organization_id, event_type, actor_user_id, "
                    "payload_json, idempotency_key, created_at "
                    "FROM pursuit_events WHERE actor_user_id = %s ORDER BY id LIMIT 5000",
                    (user_id,),
                )
            )
            return {"pursuits": pursuits, "pursuit_events": events}

    def anonymize_user_references(self, user_id: int) -> None:
        """Desvincula asignaciones mutables; el ledger permanece inalterado."""
        with connect() as conn:
            conn.execute(
                "UPDATE pursuits SET "
                "responsible_user_id = CASE WHEN responsible_user_id = %s THEN NULL "
                "ELSE responsible_user_id END, "
                "created_by_user_id = CASE WHEN created_by_user_id = %s THEN NULL "
                "ELSE created_by_user_id END, "
                "updated_by_user_id = CASE WHEN updated_by_user_id = %s THEN NULL "
                "ELSE updated_by_user_id END "
                "WHERE responsible_user_id = %s OR created_by_user_id = %s OR updated_by_user_id = %s",
                (user_id, user_id, user_id, user_id, user_id, user_id),
            )

    @staticmethod
    def _get_scoped(
        conn: Any,
        organization_id: int,
        *,
        pursuit_id: int | None = None,
        licitacion_id: str | None = None,
    ) -> dict[str, Any] | None:
        if pursuit_id is not None:
            suffix = " WHERE p.organization_id = %s AND p.id = %s"
            params: tuple[Any, ...] = (organization_id, pursuit_id)
        elif licitacion_id is not None:
            suffix = " WHERE p.organization_id = %s AND p.licitacion_id = %s"
            params = (organization_id, licitacion_id)
        else:
            raise ValueError("Se requiere pursuit_id o licitacion_id.")
        cur = conn.execute(_PURSUIT_SELECT + suffix, params)
        rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    @staticmethod
    def _event_key_exists(conn: Any, pursuit_id: int, idempotency_key: str) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM pursuit_events WHERE pursuit_id = %s AND idempotency_key = %s",
                (pursuit_id, idempotency_key),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _append_event(
        conn: Any,
        *,
        pursuit_id: int,
        organization_id: int,
        event_type: str,
        actor_user_id: int,
        payload: dict[str, Any],
        idempotency_key: str | None,
        created_at: str,
    ) -> None:
        conn.execute(
            "INSERT INTO pursuit_events "
            "(pursuit_id, organization_id, event_type, actor_user_id, "
            " payload_json, idempotency_key, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (
                pursuit_id,
                organization_id,
                event_type,
                actor_user_id,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                idempotency_key,
                created_at,
            ),
        )
