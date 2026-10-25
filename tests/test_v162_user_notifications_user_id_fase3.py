"""v162 (ADR-030 fase 3): ``user_notifications`` se teclea por ``user_id``.

Dos bloques, como ``tests/test_v135_user_id_pk_fase3.py``:

* **Unit** (sin BD): cadena de revisiones y forma del DDL —que la
  comprobación que aborta va antes del primer ``ALTER``, que el índice nuevo
  es parcial y que el ``UNIQUE`` viejo no se toca— y la convención única del
  actor de auditoría (``shared.identity.actor_del_principal``).
* **Postgres** (``tmp_db``): lo que la migración y el repositorio prometen
  sobre datos reales. La fixture aplica ``alembic upgrade head`` sobre una
  base vacía, así que el ``RAISE`` se ejercita ejecutando el SQL público de la
  revisión sobre filas sembradas.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest

_MIGRACION = "db.alembic.versions.v162_user_notifications_user_id_fase3"


def _load() -> Any:
    return importlib.import_module(_MIGRACION)


class _Inspector:
    def get_table_names(self) -> list[str]:
        return ["user_notifications", "users"]


class _PostgresOp:
    def __init__(self) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.statements: list[str] = []

    def get_bind(self) -> Any:
        return self.bind

    def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))


def _ejecutar(monkeypatch: pytest.MonkeyPatch, paso: str) -> str:
    migracion = _load()
    fake_op = _PostgresOp()
    monkeypatch.setattr(migracion, "op", fake_op)
    monkeypatch.setattr(migracion.sa, "inspect", lambda _bind: _Inspector())
    getattr(migracion, paso)()
    return "\n".join(fake_op.statements)


# ── Unit ────────────────────────────────────────────────────────────────────


def test_cadena_e_identidad() -> None:
    migracion = _load()
    assert migracion.revision == "v162_user_notifications_user_id_fase3"
    assert migracion.down_revision == "v161_documentos_sin_texto"
    assert migracion.CLAVE_NUEVA == ("user_id", "licitacion_id", "type")
    assert migracion.CLAVE_VIEJA == ("user_key", "licitacion_id", "type")


def test_clave_sql_es_la_de_v129() -> None:
    v129 = importlib.import_module("db.alembic.versions.v129_user_id_fase2")
    assert _load().CLAVE_SQL == v129.CLAVE_SQL


def test_no_hace_nada_fuera_de_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    migracion = _load()
    monkeypatch.setattr(migracion, "_is_postgres", lambda: False)

    class _FailingOp:
        def execute(self, statement: Any) -> None:
            raise AssertionError(f"SQL inesperado: {statement}")

    monkeypatch.setattr(migracion, "op", _FailingOp())
    migracion.upgrade()
    migracion.downgrade()


def test_upgrade_comprueba_antes_de_tocar_nada_y_deja_el_unique_viejo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migracion = _load()
    sql = _ejecutar(monkeypatch, "upgrade")

    assert migracion.sql_backfill() in sql
    assert "identidad(es) duplicada(s) en user_notifications" in sql
    assert sql.index("UPDATE user_notifications AS x SET user_id") < sql.index("RAISE EXCEPTION")
    assert sql.rindex("RAISE EXCEPTION") < sql.index("ALTER COLUMN user_key DROP NOT NULL")
    # Índice parcial: las filas sin id siguen tecleadas por la clave.
    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_notifications_user_id "
        "ON user_notifications (user_id, licitacion_id, type) WHERE user_id IS NOT NULL"
    ) in sql
    # Y el ``UNIQUE`` de v48 no se toca: es el árbitro del código de la fase 2
    # durante el despliegue y el de las filas sin ``user_id`` después.
    assert "DROP CONSTRAINT" not in sql
    assert "SET NOT NULL" not in sql


def test_la_comprobacion_de_duplicados_ignora_los_null_que_el_indice_no_compara() -> None:
    consulta = _load().sql_duplicados()
    assert "WHERE user_id IS NOT NULL AND licitacion_id IS NOT NULL" in consulta
    assert "GROUP BY user_id, licitacion_id, type HAVING count(*) > 1" in consulta


def test_downgrade_recupera_la_clave_y_vuelve_al_not_null(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = _ejecutar(monkeypatch, "downgrade")

    assert "SET user_key = substr(encode(sha256(" in sql
    assert "fila(s) de user_notifications sin user_key" in sql
    assert "clave(s) duplicada(s) en user_notifications por user_key, licitacion_id, type" in sql
    assert sql.rindex("RAISE EXCEPTION") < sql.index(
        "DROP INDEX IF EXISTS uq_user_notifications_user_id"
    )
    assert "ALTER COLUMN user_key SET NOT NULL" in sql


def test_el_mensaje_del_raise_escapa_las_comillas() -> None:
    bloque = _load()._exigir_vacio("SELECT 1 WHERE 'a' = 'a'", "prueba")
    assert "''a'' = ''a''" in bloque


def test_insert_sin_identidad_es_un_error_del_llamante() -> None:
    from db.notifications import insert_user_notification

    with pytest.raises(ValueError, match="user_id o user_key"):
        insert_user_notification(
            type_="t", title="t", body=None, licitacion_id="X", organization_id=1
        )


@pytest.mark.parametrize(
    ("ctx", "esperado"),
    [
        ({"user_id": 42, "user_key": "clave", "key_hash": "kh", "email": "a@b.es"}, "42"),
        ({"user_id": 0, "key_hash": "kh"}, "0"),
        ({"key_hash": "kh", "email": "a@b.es"}, None),
        ({"email": "a@b.es"}, "session"),
        ({}, "session"),
    ],
)
def test_actor_del_principal_prefiere_el_id_y_nunca_copia_el_correo(
    ctx: dict[str, Any], esperado: str | None
) -> None:
    from shared.identity import actor_del_principal

    actor = actor_del_principal(ctx)
    if esperado is None:
        # API key sin dueño: prefijo estable del hash, no la credencial.
        assert len(actor) == 16 and actor != "kh" and actor == actor_del_principal(ctx)
    else:
        assert actor == esperado
    assert "a@b.es" not in actor and "@" not in actor


# ── Postgres ────────────────────────────────────────────────────────────────


def _crear_usuario(email: str) -> int:
    from db.database import connect, now_utc_iso

    with connect() as c:
        fila = c.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (%s, 'h', %s) "
            "RETURNING id",
            (email, now_utc_iso()),
        ).fetchone()
    return int(fila[0])


def _organizacion_personal(user_id: int) -> int:
    from db.repositories.organizations import OrganizationRepository

    return int(OrganizationRepository().ensure_personal_organization(user_id)["id"])


def _filas(user_id: int) -> list[tuple[Any, ...]]:
    from db.database import connect

    with connect() as c:
        return [
            tuple(f)
            for f in c.execute(
                "SELECT user_key, licitacion_id, type FROM user_notifications "
                "WHERE user_id = %s ORDER BY id",
                (user_id,),
            ).fetchall()
        ]


def _alerta(**extra: Any) -> bool:
    from db.notifications import insert_user_notification

    base: dict[str, Any] = {
        "type_": "deadline_7",
        "title": "Plazo",
        "body": None,
        "licitacion_id": "LIC-1",
    }
    base.update(extra)
    return insert_user_notification(**base)


def test_con_user_id_la_alerta_nace_sin_clave_y_la_base_impide_el_duplicado(tmp_db: Any) -> None:
    """Dos claves de dos correos del mismo usuario caen en la misma fila: lo
    impide el índice parcial, no un ``SELECT`` previo del repositorio."""
    user_id = _crear_usuario("alerta@v162.test")
    org = _organizacion_personal(user_id)

    assert _alerta(user_id=user_id, user_key="clave-vieja", organization_id=org) is True
    assert _alerta(user_id=user_id, user_key="clave-nueva", organization_id=org) is False
    assert _alerta(user_id=user_id, organization_id=org) is False
    # Otro tipo u otro expediente sí son alertas distintas.
    assert _alerta(user_id=user_id, organization_id=org, type_="deadline_1") is True
    assert _alerta(user_id=user_id, organization_id=org, licitacion_id="LIC-2") is True

    assert _filas(user_id) == [
        (None, "LIC-1", "deadline_7"),
        (None, "LIC-1", "deadline_1"),
        (None, "LIC-2", "deadline_7"),
    ]


def test_la_alerta_escrita_por_la_fase_2_frena_a_la_nueva(tmp_db: Any) -> None:
    """Una fila con las dos columnas (código anterior a v162, o un correo
    anterior) y la nueva sin clave son la misma alerta."""
    from db.database import connect, now_utc_iso

    user_id = _crear_usuario("transicion@v162.test")
    org = _organizacion_personal(user_id)
    with connect() as c:
        c.execute(
            "INSERT INTO user_notifications "
            "(user_key, user_id, created_at, type, title, licitacion_id, organization_id) "
            "VALUES ('k-fase2', %s, %s, 'deadline_7', 'Plazo', 'LIC-1', %s) "
            "ON CONFLICT (user_key, licitacion_id, type) DO NOTHING",
            (user_id, now_utc_iso(), org),
        )
    assert _alerta(user_id=user_id, organization_id=org) is False
    assert _filas(user_id) == [("k-fase2", "LIC-1", "deadline_7")]


def test_sin_user_id_sigue_valiendo_la_clave(tmp_db: Any) -> None:
    """Favoritos que el backfill no resolvió: la alerta sale sólo con clave y
    la identidad vieja sigue deduplicando."""
    user_id = _crear_usuario("legacy@v162.test")
    org = _organizacion_personal(user_id)
    assert _alerta(user_key="solo-clave", organization_id=org) is True
    assert _alerta(user_key="solo-clave", organization_id=org) is False

    from db.notifications import alertas_de_usuario

    # La lectura dual la sirve por clave, y no se la enseña a un id ajeno.
    assert [a["licitacion_id"] for a in alertas_de_usuario("solo-clave", 10, org)] == ["LIC-1"]
    assert alertas_de_usuario("otra", 10, org, user_id=user_id) == []


def test_la_bandeja_y_el_gdpr_ven_la_alerta_sin_clave_tras_cambiar_de_correo(
    tmp_db: Any,
) -> None:
    from services.gdpr import anonymize_user_data, export_user_notifications
    from shared.identity import user_key_from_email

    user_id = _crear_usuario("Antes@v162.test")
    org = _organizacion_personal(user_id)
    assert _alerta(user_id=user_id, organization_id=org) is True

    clave_nueva = user_key_from_email("despues@v162.test", user_id)
    assert [
        a["licitacion_id"] for a in export_user_notifications(clave_nueva, user_id=user_id)
    ] == ["LIC-1"]
    anonymize_user_data(clave_nueva, user_id=user_id)
    assert _filas(user_id) == []


def test_la_campana_lee_una_alerta_escrita_solo_con_user_id(tmp_db: Any) -> None:
    """Una fila con una sola identidad (``user_id``, sin clave) la ven el
    listado, el badge y «marcar todas», leyendo con la clave que toque: la
    lectura dual cubre filas con una sola de las dos columnas. Y un lector que
    sólo trae clave —un favorito sin id— no la ve, porque no es suya."""
    from db.notifications import (
        alertas_de_usuario,
        contar_alertas_sin_leer,
        listar_alertas,
        marcar_todas_alertas_leidas,
    )
    from shared.identity import user_key_from_email

    user_id = _crear_usuario("Solo-Id@v162.test")
    org = _organizacion_personal(user_id)
    assert _alerta(user_id=user_id, organization_id=org) is True
    clave = user_key_from_email("otro-correo@v162.test", user_id)

    assert [a["licitacion_id"] for a in alertas_de_usuario(clave, 10, org, user_id=user_id)] == [
        "LIC-1"
    ]
    pagina = listar_alertas(clave, org, user_id=user_id, estado="sin_leer")
    assert pagina["total"] == 1
    assert contar_alertas_sin_leer(clave, org, user_id=user_id) == 1
    marcar_todas_alertas_leidas(clave, org, user_id=user_id)
    assert contar_alertas_sin_leer(clave, org, user_id=user_id) == 0
    assert listar_alertas(clave, org, user_id=user_id, estado="leidas")["total"] == 1

    # Un lector sin id (clave sola) no la ve: la fila no lleva clave.
    assert alertas_de_usuario(clave, 10, org) == []
    assert contar_alertas_sin_leer(clave, org) == 0


def test_la_comprobacion_aborta_con_dos_avisos_de_la_misma_persona(tmp_db: Any) -> None:
    """El ``RAISE`` de la migración salta ante dos filas con el mismo
    ``(user_id, licitacion_id, type)``; el índice parcial impide crearlas
    sobre el schema ya migrado, así que se prueba contra una tabla temporal
    con la misma forma, con el nombre de la real sustituido."""
    import psycopg

    from db.database import connect

    migracion = _load()
    consulta = migracion.sql_duplicados().replace("FROM user_notifications", "FROM v162_prueba")
    # Exactamente un grupo: el par con ``licitacion_id IS NULL`` no cuenta,
    # porque tampoco chocaría en el índice.
    with pytest.raises(psycopg.errors.RaiseException, match="v162: 1 identidad"), connect() as c:
        c.execute(
            "CREATE TEMPORARY TABLE v162_prueba "
            "(user_key TEXT, user_id INTEGER, licitacion_id TEXT, type TEXT) ON COMMIT DROP"
        )
        c.execute(
            "INSERT INTO v162_prueba VALUES ('k1', 7, 'LIC-1', 't'), ('k2', 7, 'LIC-1', 't'), "
            "('k3', 7, NULL, 't'), ('k4', 7, NULL, 't')"
        )
        c.execute(migracion._exigir_vacio(consulta, "identidad(es) duplicada(s)"))
