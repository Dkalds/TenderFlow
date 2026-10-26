"""v165 (ADR-030 fase 3, tercera tanda): ``notification_reads``,
``user_event_prefs`` y ``saved_filters`` se teclean por ``user_id``.

Mismo esquema que ``tests/test_v162_user_notifications_user_id_fase3.py``:

* **Unit** (sin BD): cadena de revisiones, forma del DDL —backfill, fusión de
  marcas de lectura y comprobaciones antes del primer ``ALTER``, índices
  parciales, ``UNIQUE`` viejo intacto— y el SQL que emiten los escritores con
  y sin ``user_id``.
* **Postgres** (``tmp_db``): lo que la migración y los repositorios prometen
  sobre datos reales. La fixture aplica ``alembic upgrade head`` sobre una base
  vacía, así que la fusión y el ``RAISE`` se ejercitan ejecutando el SQL
  público de la revisión sobre una tabla temporal con la misma forma.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_MIGRACION = "db.alembic.versions.v165_user_id_fase3_tanda3"


def _load() -> Any:
    return importlib.import_module(_MIGRACION)


class _Inspector:
    def get_table_names(self) -> list[str]:
        return ["notification_reads", "user_event_prefs", "saved_filters", "users"]


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


def _conexion_simulada(rowcount: int = 0) -> tuple[MagicMock, MagicMock]:
    conn = MagicMock()
    conn.execute.return_value.rowcount = rowcount
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=ctx), conn


def _sql(llamada: Any) -> str:
    return " ".join(str(llamada[0][0]).split())


# ── Unit: la migración ──────────────────────────────────────────────────────


def test_cadena_e_identidad() -> None:
    migracion = _load()
    assert migracion.revision == "v165_user_id_fase3_tanda3"
    assert migracion.down_revision == "v164_identidad_placsp_rekey"
    assert migracion.TABLAS == {
        "notification_reads": "notification_id",
        "user_event_prefs": "event_type",
        "saved_filters": "name",
    }
    assert frozenset({"notification_reads"}) == migracion.SE_DEDUPLICAN


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


def test_upgrade_resuelve_fusiona_y_comprueba_antes_de_tocar_nada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migracion = _load()
    sql = _ejecutar(monkeypatch, "upgrade")

    for tabla in migracion.TABLAS:
        assert migracion.sql_backfill(tabla) in sql
        assert f"identidad(es) duplicada(s) en {tabla}" in sql
    # Orden: backfill → fusión de marcas → comprobaciones → primer DDL.
    ultimo_backfill = sql.rindex("SET user_id = k.user_id")
    fusion = sql.index(migracion.sql_deduplicar_lecturas())
    assert ultimo_backfill < fusion < sql.index("RAISE EXCEPTION")
    assert sql.rindex("RAISE EXCEPTION") < sql.index("ALTER COLUMN user_key DROP NOT NULL")


def test_upgrade_crea_indices_parciales_y_deja_el_unique_viejo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sql = _ejecutar(monkeypatch, "upgrade")

    for tabla, columna in _load().TABLAS.items():
        assert f"ALTER TABLE {tabla} ALTER COLUMN user_key DROP NOT NULL" in sql
        assert (
            f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{tabla}_user_id "
            f"ON {tabla} (user_id, {columna}) WHERE user_id IS NOT NULL"
        ) in sql
    # El ``UNIQUE`` por clave sigue: árbitro del código anterior durante el
    # despliegue y de las filas sin ``user_id`` después.
    assert "DROP CONSTRAINT" not in sql
    assert "SET NOT NULL" not in sql


def test_solo_se_fusionan_las_marcas_de_lectura() -> None:
    """Preferencias y vistas duplicadas son decisión humana: abortan."""
    migracion = _load()
    fusion = migracion.sql_deduplicar_lecturas()
    assert fusion.startswith("DELETE FROM notification_reads AS a USING notification_reads AS b")
    # Se queda la marca más reciente: la última visita (MAX(read_at)) no cambia.
    assert "(a.read_at, a.id) < (b.read_at, b.id)" in fusion
    assert "user_event_prefs" not in fusion and "saved_filters" not in fusion


def test_la_comprobacion_ignora_los_null_que_el_indice_no_compara() -> None:
    consulta = _load().sql_duplicados("saved_filters")
    assert "WHERE user_id IS NOT NULL" in consulta
    assert "GROUP BY user_id, name HAVING count(*) > 1" in consulta
    vieja = _load().sql_duplicados("user_event_prefs", "user_key")
    assert "GROUP BY user_key, event_type HAVING count(*) > 1" in vieja


def test_downgrade_recupera_la_clave_y_vuelve_al_not_null(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = _ejecutar(monkeypatch, "downgrade")

    for tabla, columna in _load().TABLAS.items():
        assert f"{tabla} AS x SET user_key = substr(encode(sha256(" in sql
        assert f"fila(s) de {tabla} sin user_key" in sql
        assert f"clave(s) duplicada(s) en {tabla} por user_key, {columna}" in sql
        assert f"DROP INDEX IF EXISTS uq_{tabla}_user_id" in sql
        assert f"ALTER TABLE {tabla} ALTER COLUMN user_key SET NOT NULL" in sql
    assert sql.rindex("RAISE EXCEPTION") < sql.index("DROP INDEX IF EXISTS")


def test_el_mensaje_del_raise_escapa_las_comillas() -> None:
    bloque = _load()._exigir_vacio("SELECT 1 WHERE 'a' = 'a'", "prueba")
    assert "''a'' = ''a''" in bloque
    assert "'v165: % prueba." in bloque


# ── Unit: lo que escriben los repositorios ──────────────────────────────────


@pytest.mark.parametrize(
    ("user_id", "clave", "arbitro"),
    [
        (7, None, "ON CONFLICT (user_id, notification_id) WHERE user_id IS NOT NULL"),
        (None, "k", "ON CONFLICT (user_key, notification_id)"),
    ],
)
def test_las_marcas_de_lectura_con_id_nacen_sin_clave(
    user_id: int | None, clave: str | None, arbitro: str
) -> None:
    from db import notifications

    connect, conn = _conexion_simulada()
    with patch.object(notifications, "connect", connect):
        notifications.mark_read("k", "LIC-1", user_id=user_id)
        notifications.marcar_visita("k", user_id=user_id)

    insertar, visita = conn.executemany.call_args, conn.execute.call_args
    assert f"{arbitro} DO NOTHING" in _sql(insertar)
    assert insertar[0][1][0][:3] == (clave, user_id, "LIC-1")
    assert f"{arbitro} DO UPDATE SET read_at = excluded.read_at" in _sql(visita)
    assert visita[0][1][:3] == (clave, user_id, notifications.MARCA_VISITA)


def test_la_preferencia_con_id_nace_sin_clave_y_arbitra_por_id() -> None:
    from db import notifications

    connect, conn = _conexion_simulada(rowcount=0)
    with patch.object(notifications, "connect", connect):
        notifications.guardar_modo_email("k", "pursuit.assigned", "off", user_id=7)

    actualizar, insertar = conn.execute.call_args_list
    # El UPDATE no adopta el id si la fila del id ya existe (índice de v165).
    assert "CASE WHEN EXISTS (SELECT 1 FROM user_event_prefs o" in _sql(actualizar)
    parametros = actualizar[0][1]
    assert parametros[0] == "off"
    assert parametros[2:] == (7, 7, 7, "k", 7, "pursuit.assigned")
    assert "ON CONFLICT (user_id, event_type) WHERE user_id IS NOT NULL DO UPDATE" in _sql(insertar)
    assert insertar[0][1][:3] == (None, 7, "pursuit.assigned")


def test_la_vista_con_id_nace_sin_clave_y_arbitra_por_id() -> None:
    from db import saved_filters

    connect, conn = _conexion_simulada(rowcount=0)
    with patch.object(saved_filters, "connect", connect):
        saved_filters.save_filter("k", "Mi vista", "{}", 3, user_id=7)

    actualizar, insertar = conn.execute.call_args_list
    assert "CASE WHEN EXISTS (SELECT 1 FROM saved_filters o" in _sql(actualizar)
    assert "ON CONFLICT (user_id, name) WHERE user_id IS NOT NULL DO UPDATE" in _sql(insertar)
    assert insertar[0][1][:3] == (None, 7, "Mi vista")


def test_la_lectura_de_preferencia_prefiere_la_fila_del_id() -> None:
    from db import notifications

    cursor = MagicMock()
    cursor.fetchone.return_value = ("off",)
    conn = MagicMock()
    conn.execute.return_value = cursor
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=conn)
    ctx.__exit__ = MagicMock(return_value=False)
    with patch.object(notifications, "connect_read", MagicMock(return_value=ctx)):
        assert notifications.leer_modo_email("k", "pursuit.assigned", user_id=7) == "off"

    llamada = conn.execute.call_args
    assert "CASE WHEN user_id = %s THEN 0 WHEN user_key = %s THEN 1 ELSE 2 END" in _sql(llamada)
    assert llamada[0][1] == (7, "k", 7, "pursuit.assigned", 7, "k")


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


def _filas(tabla: str, columna: str, user_id: int) -> list[tuple[Any, ...]]:
    from db.database import connect

    with connect() as c:
        return [
            tuple(f)
            for f in c.execute(
                f"SELECT user_key, {columna} FROM {tabla} WHERE user_id = %s ORDER BY id",  # noqa: S608
                (user_id,),
            ).fetchall()
        ]


def test_marcas_de_lectura_por_id_sobreviven_al_cambio_de_correo(tmp_db: Any) -> None:
    """Dos claves del mismo usuario marcan la misma notificación una vez; lo
    impide el índice parcial. La última visita es una fila y se mueve."""
    from db.notifications import (
        MARCA_VISITA,
        get_last_seen_ts,
        get_unread_ids,
        marcar_visita,
        mark_read,
    )

    user_id = _crear_usuario("lecturas@v165.test")
    mark_read("clave-vieja", "LIC-1", user_id=user_id)
    mark_read("clave-nueva", "LIC-1", user_id=user_id)
    primera = marcar_visita("clave-vieja", user_id=user_id)
    segunda = marcar_visita("clave-nueva", user_id=user_id)

    assert _filas("notification_reads", "notification_id", user_id) == [
        (None, "LIC-1"),
        (None, MARCA_VISITA),
    ]
    assert segunda >= primera
    assert get_last_seen_ts("otra-clave", user_id=user_id) == segunda
    assert get_unread_ids("otra-clave", ["LIC-1", "LIC-2"], user_id=user_id) == ["LIC-2"]
    # Un lector con sólo la clave no ve marcas que no llevan clave.
    assert get_unread_ids("clave-nueva", ["LIC-1"]) == ["LIC-1"]


def test_la_marca_escrita_por_la_fase_2_frena_a_la_nueva(tmp_db: Any) -> None:
    from db.database import connect, now_utc_iso
    from db.notifications import mark_read

    user_id = _crear_usuario("transicion-lecturas@v165.test")
    with connect() as c:
        c.execute(
            "INSERT INTO notification_reads (user_key, user_id, notification_id, read_at) "
            "VALUES ('k-fase2', %s, 'LIC-1', %s)",
            (user_id, now_utc_iso()),
        )
    mark_read("k-nueva", "LIC-1", user_id=user_id)
    assert _filas("notification_reads", "notification_id", user_id) == [("k-fase2", "LIC-1")]


def test_sin_user_id_las_marcas_siguen_por_clave(tmp_db: Any) -> None:
    from db.notifications import get_last_seen_ts, get_unread_ids, marcar_visita, mark_read

    mark_read("solo-clave", "LIC-1")
    mark_read("solo-clave", "LIC-1")
    marca = marcar_visita("solo-clave")
    marcar_visita("solo-clave")
    assert get_unread_ids("solo-clave", ["LIC-1", "LIC-2"]) == ["LIC-2"]
    assert str(get_last_seen_ts("solo-clave")) >= marca


def test_preferencia_por_id_sin_clave_y_sin_duplicar(tmp_db: Any) -> None:
    from services.notifications import modo_email_de, set_modo_email

    user_id = _crear_usuario("prefs@v165.test")
    set_modo_email("clave-vieja", "pursuit.assigned", "off", user_id=user_id)
    set_modo_email("clave-nueva", "pursuit.assigned", "daily", user_id=user_id)

    assert _filas("user_event_prefs", "event_type", user_id) == [(None, "pursuit.assigned")]
    assert modo_email_de("otra-clave", "pursuit.assigned", user_id=user_id) == "daily"
    # Sin id, la fila sin clave no es de nadie que sólo traiga clave.
    assert modo_email_de("clave-nueva", "pursuit.assigned") == "immediate"


def test_preferencia_sin_resolver_junto_a_la_del_id_no_rompe_el_indice(tmp_db: Any) -> None:
    """Una fila que el backfill no resolvió (clave, sin id) y la del id para
    el mismo evento: guardar no puede adoptar el id en la primera, o violaría
    el índice parcial. Se actualizan las dos y la lectura prefiere la del id."""
    from db.database import connect, now_utc_iso
    from services.notifications import modo_email_de, set_modo_email

    user_id = _crear_usuario("prefs-mezcla@v165.test")
    set_modo_email("k", "pursuit.assigned", "off", user_id=user_id)
    with connect() as c:
        c.execute(
            "INSERT INTO user_event_prefs (user_key, user_id, event_type, modo, updated_at) "
            "VALUES ('k', NULL, 'pursuit.assigned', 'immediate', %s)",
            (now_utc_iso(),),
        )

    set_modo_email("k", "pursuit.assigned", "daily", user_id=user_id)

    assert _filas("user_event_prefs", "event_type", user_id) == [(None, "pursuit.assigned")]
    with connect() as c:
        sin_id = c.execute(
            "SELECT modo FROM user_event_prefs WHERE user_key = 'k' AND user_id IS NULL"
        ).fetchall()
    assert [f[0] for f in sin_id] == ["daily"]
    assert modo_email_de("k", "pursuit.assigned", user_id=user_id) == "daily"


def test_la_preferencia_sin_resolver_adopta_el_id_si_no_hay_otra(tmp_db: Any) -> None:
    from db.database import connect, now_utc_iso
    from services.notifications import set_modo_email

    user_id = _crear_usuario("prefs-adopta@v165.test")
    with connect() as c:
        c.execute(
            "INSERT INTO user_event_prefs (user_key, user_id, event_type, modo, updated_at) "
            "VALUES ('k-sola', NULL, 'pursuit.assigned', 'immediate', %s)",
            (now_utc_iso(),),
        )
    set_modo_email("k-sola", "pursuit.assigned", "off", user_id=user_id)
    assert _filas("user_event_prefs", "event_type", user_id) == [("k-sola", "pursuit.assigned")]


def test_vista_por_id_sin_clave_y_sin_duplicar(tmp_db: Any) -> None:
    from db.saved_filters import list_saved_filters, save_filter

    user_id = _crear_usuario("vistas@v165.test")
    org = _organizacion_personal(user_id)
    save_filter("clave-vieja", "Mi vista", '{"q":"a"}', org, user_id=user_id)
    save_filter("clave-nueva", "Mi vista", '{"q":"b"}', org, user_id=user_id)

    assert _filas("saved_filters", "name", user_id) == [(None, "Mi vista")]
    vistas = list_saved_filters("otra-clave", org, user_id=user_id)
    assert [(v["name"], v["filters_json"]) for v in vistas] == [("Mi vista", '{"q":"b"}')]


def test_vista_sin_resolver_junto_a_la_del_id_no_rompe_el_indice(tmp_db: Any) -> None:
    from db.database import connect, now_utc_iso
    from db.saved_filters import save_filter

    user_id = _crear_usuario("vistas-mezcla@v165.test")
    org = _organizacion_personal(user_id)
    save_filter("k", "Mi vista", "{}", org, user_id=user_id)
    with connect() as c:
        c.execute(
            "INSERT INTO saved_filters "
            "(user_key, user_id, name, filters_json, created_at, organization_id, visibility) "
            "VALUES ('k', NULL, 'Mi vista', '{}', %s, %s, 'private')",
            (now_utc_iso(), org),
        )
    save_filter("k", "Mi vista", '{"q":"c"}', org, user_id=user_id)
    assert _filas("saved_filters", "name", user_id) == [(None, "Mi vista")]


def test_la_fusion_de_marcas_conserva_la_ultima_visita(tmp_db: Any) -> None:
    """La fusión de la migración, sobre una tabla temporal con la misma forma."""
    from db.database import connect

    fusion = _load().sql_deduplicar_lecturas().replace("notification_reads", "v165_lecturas")
    with connect() as c:
        c.execute(
            "CREATE TEMPORARY TABLE v165_lecturas (id INTEGER, user_key TEXT, "
            "user_id INTEGER, notification_id TEXT, read_at TEXT) ON COMMIT DROP"
        )
        c.execute(
            "INSERT INTO v165_lecturas VALUES "
            "(1, 'k1', 7, 'LIC-1', '2026-10-01'), (2, 'k2', 7, 'LIC-1', '2026-10-05'), "
            "(3, 'k1', 7, 'LIC-2', '2026-10-02'), (4, 'k3', NULL, 'LIC-1', '2026-09-01'), "
            "(5, 'k4', NULL, 'LIC-1', '2026-09-02')"
        )
        c.execute(fusion)
        quedan = c.execute("SELECT id FROM v165_lecturas ORDER BY id").fetchall()
    # Se va la marca vieja del mismo usuario; las sin id no se tocan.
    assert [f[0] for f in quedan] == [2, 3, 4, 5]


def test_la_comprobacion_aborta_con_dos_vistas_homonimas_de_la_misma_persona(
    tmp_db: Any,
) -> None:
    import psycopg

    from db.database import connect

    migracion = _load()
    consulta = migracion.sql_duplicados("saved_filters").replace(
        "FROM saved_filters", "FROM v165_prueba"
    )
    with pytest.raises(psycopg.errors.RaiseException, match="v165: 1 identidad"), connect() as c:
        c.execute(
            "CREATE TEMPORARY TABLE v165_prueba "
            "(user_key TEXT, user_id INTEGER, name TEXT) ON COMMIT DROP"
        )
        c.execute(
            "INSERT INTO v165_prueba VALUES ('k1', 7, 'Mi vista'), ('k2', 7, 'Mi vista'), "
            "('k3', NULL, 'Mi vista'), ('k4', NULL, 'Mi vista')"
        )
        c.execute(migracion._exigir_vacio(consulta, "identidad(es) duplicada(s)"))
