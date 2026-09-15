"""RLS por tenant (``v128``) y ámbito de organización (ADR-034), contra Postgres.

Qué se prueba
-------------
1. Con ámbito fijado (``shared.tenant_context``), un ``SELECT`` crudo por
   ``db.connection.connect_read()`` solo devuelve filas de esa organización —
   y sigue viendo las filas legadas con ``organization_id NULL``.
2. Un ``INSERT``/``UPDATE`` que produzca una fila de otra organización dentro
   del ámbito falla en la base de datos, no en la aplicación.
3. Sin ámbito se ve todo, incluso en una conexión del pool que ya pasó por
   una transacción acotada (el GUC vuelve a ``''``, no a ``NULL``).
4. ``api.concurrency.run_db`` lleva el ámbito al hilo del pool y la
   transacción que abre allí queda acotada.
5. Una ruta que pasa por ``api/tenancy.py`` fija el ámbito y no filtra nada
   de otra organización.
6. Estructural: toda tabla con ``organization_id`` está en el conjunto
   ``FORCE + políticas`` de ``v128`` o en la lista de exclusiones de este
   archivo. Una tabla nueva no entra sin decisión.

Por qué un rol sonda
--------------------
El rol de la suite (y el del ``docker compose`` local) es **superusuario**, y
los superusuarios bypassan la RLS aunque la tabla tenga ``FORCE``. Sin esto,
las políticas serían invisibles para la suite entera y el primer rol en
ejercerlas sería ``tenderflow_app`` en producción. El fixture ``rol_runtime``
crea un rol sin ``BYPASSRLS``, le da a cada tabla del schema del test la misma
política ``USING (true)`` que ``scripts/setup_pg_roles.sql`` da a
``tenderflow_app``, y hace que el pool conecte con ``SET ROLE``. Es la
configuración de producción tal cual: si la política de ``v128`` fuera solo
permisiva, ``true OR predicado`` la anularía y estos tests lo dirían.
"""

from __future__ import annotations

import importlib
import os
import secrets
from collections.abc import Callable, Iterator
from typing import Any

import anyio
import pytest

from shared.tenant_context import current_organization, tenant_scope

#: Tablas con ``organization_id`` que **no** llevan políticas por tenant, con
#: el motivo. Añadir una entrada aquí es una decisión, no un atajo: hay que
#: poder explicar por qué esa tabla debe leerse a través de organizaciones.
TABLAS_EXCLUIDAS: dict[str, str] = {
    "organization_memberships": (
        "resolver la membresía de una petición exige ver todas las "
        "organizaciones del usuario antes de tener ámbito"
    ),
    "organization_invitations": (
        "las invitaciones se aceptan y listan por correo, a través de organizaciones"
    ),
    "domain_events": "outbox (ADR-027): el dispatcher lo consume sin ámbito",
    "jobs": "cola de trabajo (ADR-028): el worker la consume sin ámbito",
}


#: Revisiones que declaran tablas corporativas protegidas. v128 protegió las 29
#: que ya existían; desde entonces la regla es que **cada migración protege las
#: tablas que crea**, y no que se amplíe la lista de v128 —que ya no se vuelve a
#: ejecutar—. Cada revisión nueva con tablas corporativas se añade aquí.
_REVISIONES_CON_TABLAS: tuple[str, ...] = (
    "v128_rls_tenant_policies",
    "v130_follows",
    "v132_informes_programados",
)


def _migracion() -> Any:
    return importlib.import_module("db.alembic.versions.v128_rls_tenant_policies")


def _tablas_corporativas() -> set[str]:
    """Unión de las tablas corporativas declaradas por todas las revisiones."""
    tablas: set[str] = set()
    for revision in _REVISIONES_CON_TABLAS:
        modulo = importlib.import_module(f"db.alembic.versions.{revision}")
        tablas |= set(modulo.TABLAS_CORPORATIVAS)
    return tablas


# ── Rol sonda que emula a tenderflow_app ───────────────────────────────────


@pytest.fixture()
def rol_runtime(tmp_db: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Hace que ambos pools conecten como un rol no-superusuario con acceso total.

    El rol es efímero y con nombre único por test (los roles son globales al
    clúster y ``-n auto`` corre tests en paralelo). Al salir, ``DROP OWNED BY``
    retira grants y políticas ``TO rol`` y ``DROP ROLE`` lo elimina.
    """
    db_mod, _ = tmp_db
    import db.connection as conn_mod

    rol = f"tf_rls_probe_{os.getpid()}_{secrets.token_hex(4)}"
    with db_mod.connect() as c:
        schema = str(c.execute("SELECT current_schema()").fetchone()[0])
        c.execute(f'CREATE ROLE "{rol}" NOLOGIN NOBYPASSRLS')
        c.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{rol}"')
        c.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{rol}"'
        )
        c.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{rol}"')
        tablas = [
            str(r[0])
            for r in c.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = %s", (schema,)
            ).fetchall()
        ]
        for tabla in tablas:
            # Réplica de `tenderflow_app_full_access` (scripts/setup_pg_roles.sql §3).
            c.execute(
                f'CREATE POLICY tf_probe_full_access ON "{schema}"."{tabla}" '
                f'FOR ALL TO "{rol}" USING (true) WITH CHECK (true)'
            )
    db_mod.close_pool()

    original = conn_mod._make_pg_configure

    def _configure_como_sonda(*, read_only: bool) -> Callable[[Any], None]:
        base = original(read_only=read_only)

        def _configure(conn: Any) -> None:
            base(conn)
            conn.execute(f'SET ROLE "{rol}"')
            if not getattr(conn, "autocommit", False):
                conn.commit()

        return _configure

    monkeypatch.setattr(conn_mod, "_make_pg_configure", _configure_como_sonda)
    try:
        yield rol
    finally:
        monkeypatch.setattr(conn_mod, "_make_pg_configure", original)
        db_mod.close_pool()
        with db_mod.connect() as c:
            c.execute(f'DROP OWNED BY "{rol}"')
            c.execute(f'DROP ROLE "{rol}"')
        db_mod.close_pool()


# ── Semilla: dos organizaciones con datos en cada una ─────────────────────


def _sembrar(db_mod: Any) -> dict[str, int]:
    """Dos usuarios, sus organizaciones personales, un pursuit y un favorito en cada una.

    Corre sin ámbito: es lo que haría el scraper o un script, y demuestra de
    paso que el paso franco de las políticas no rompe las escrituras normales.
    """
    from db.repositories.organizations import OrganizationRepository
    from db.repositories.pursuits import PursuitRepository
    from db.users import create_user

    orgs = OrganizationRepository()
    user_a = create_user(
        email="rls-a@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
        display_name="Usuario A",
    )
    user_b = create_user(
        email="rls-b@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
        display_name="Usuario B",
    )
    org_a = int(orgs.ensure_personal_organization(user_a)["id"])
    org_b = int(orgs.ensure_personal_organization(user_b)["id"])
    assert org_a != org_b

    with db_mod.connect() as c:
        c.executemany(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_limite, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s)",
            [
                (
                    "LIC-RLS-A",
                    "Expediente de A",
                    "2026-11-01T10:00:00+00:00",
                    "2026-09-01T00:00:00+00:00",
                ),
                (
                    "LIC-RLS-B",
                    "Expediente de B",
                    "2026-11-01T10:00:00+00:00",
                    "2026-09-01T00:00:00+00:00",
                ),
            ],
        )
        c.executemany(
            "INSERT INTO watchlist_items (user_key, user_id, id_externo, organization_id, visibility) "
            "VALUES (%s, %s, %s, %s, %s)",
            [
                ("rls-a", user_a, "LIC-RLS-A", org_a, "private"),
                ("rls-b", user_b, "LIC-RLS-B", org_b, "private"),
                # Fila legada sin organización (db/tenancy_backfill.py): debe
                # seguir visible desde cualquier ámbito.
                ("rls-legacy", user_a, "LIC-RLS-B", None, "private"),
            ],
        )

    pursuits = PursuitRepository()
    pursuits.create(
        organization_id=org_a,
        licitacion_id="LIC-RLS-A",
        responsible_user_id=None,
        actor_user_id=user_a,
    )
    pursuits.create(
        organization_id=org_b,
        licitacion_id="LIC-RLS-B",
        responsible_user_id=None,
        actor_user_id=user_b,
    )
    return {"user_a": user_a, "user_b": user_b, "org_a": org_a, "org_b": org_b}


def _organizaciones_visibles(db_mod: Any, tabla: str) -> list[int | None]:
    with db_mod.connect_read() as c:
        # `tabla` es un literal de este archivo, nunca entrada externa.
        cur = c.execute(f"SELECT organization_id FROM {tabla}")  # noqa: S608
        return [r[0] for r in cur.fetchall()]


# ── 1-3: lectura y escritura crudas ────────────────────────────────────────


def test_lectura_con_ambito_solo_ve_su_organizacion(rol_runtime: str, tmp_db: Any) -> None:
    from psycopg.pq import TransactionStatus

    db_mod, _ = tmp_db
    s = _sembrar(db_mod)

    with tenant_scope(s["org_a"]), db_mod.connect_read() as c:
        pursuits = [r[0] for r in c.execute("SELECT organization_id FROM pursuits").fetchall()]
        favoritos = [
            r[0] for r in c.execute("SELECT organization_id FROM watchlist_items").fetchall()
        ]
        eventos = [r[0] for r in c.execute("SELECT organization_id FROM pursuit_events").fetchall()]
        # La lectura acotada corre dentro de una transacción explícita: es lo
        # que hace que el SET LOCAL tenga efecto en una conexión en autocommit.
        assert c._conn.info.transaction_status == TransactionStatus.INTRANS

    assert pursuits == [s["org_a"]]
    assert eventos == [s["org_a"]]
    assert sorted(favoritos, key=lambda v: (v is None, v or 0)) == [s["org_a"], None]
    assert s["org_b"] not in favoritos


def test_escribir_para_otra_organizacion_dentro_del_ambito_falla(
    rol_runtime: str, tmp_db: Any
) -> None:
    import psycopg

    db_mod, _ = tmp_db
    s = _sembrar(db_mod)

    with tenant_scope(s["org_a"]):
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"),
            db_mod.connect() as c,
        ):
            c.execute(
                "INSERT INTO watchlist_items "
                "(user_key, user_id, id_externo, organization_id, visibility) "
                "VALUES (%s, %s, %s, %s, %s)",
                ("rls-intruso", s["user_a"], "LIC-RLS-B", s["org_b"], "private"),
            )
        # Control positivo: la propia organización sí puede escribir.
        with db_mod.connect() as c:
            c.execute(
                "INSERT INTO watchlist_items "
                "(user_key, user_id, id_externo, organization_id, visibility) "
                "VALUES (%s, %s, %s, %s, %s)",
                ("rls-a-bis", s["user_a"], "LIC-RLS-B", s["org_a"], "private"),
            )
        # Mover una fila a otra organización tampoco: WITH CHECK cubre UPDATE.
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"),
            db_mod.connect() as c,
        ):
            c.execute(
                "UPDATE watchlist_items SET organization_id = %s WHERE organization_id = %s",
                (s["org_b"], s["org_a"]),
            )

    # El rollback del bloque fallido no dejó rastro y la fila legítima sí está.
    visibles = _organizaciones_visibles(db_mod, "watchlist_items")
    assert visibles.count(s["org_a"]) == 2
    assert visibles.count(s["org_b"]) == 1
    with db_mod.connect_read() as c:
        claves = {r[0] for r in c.execute("SELECT user_key FROM watchlist_items").fetchall()}
    assert "rls-a-bis" in claves
    assert "rls-intruso" not in claves


def test_sin_ambito_se_ve_todo_incluso_tras_una_transaccion_acotada(
    rol_runtime: str, tmp_db: Any
) -> None:
    """El GUC vuelve a ``''`` (no a NULL) tras un ``SET LOCAL``: sigue siendo paso franco."""
    from psycopg.pq import TransactionStatus

    db_mod, _ = tmp_db
    s = _sembrar(db_mod)

    with tenant_scope(s["org_a"]), db_mod.connect_read() as c:
        pid_acotado = int(c.execute("SELECT pg_backend_pid()").fetchone()[0])

    pids: set[int] = set()
    for _ in range(3):
        with db_mod.connect_read() as c:
            pids.add(int(c.execute("SELECT pg_backend_pid()").fetchone()[0]))
            guc = c.execute("SELECT current_setting('app.organization_id', true)").fetchone()[0]
            assert guc in (None, "")
            vistas = {r[0] for r in c.execute("SELECT organization_id FROM pursuits").fetchall()}
            # Sin ámbito no se abre transacción: la lectura sigue costando un viaje.
            assert c._conn.info.transaction_status == TransactionStatus.IDLE
        assert vistas == {s["org_a"], s["org_b"]}

    # El pool de lectura reutilizó la conexión que ya pasó por el SET LOCAL.
    assert pid_acotado in pids

    with db_mod.connect() as c:
        vistas_escritura = {
            r[0] for r in c.execute("SELECT organization_id FROM pursuits").fetchall()
        }
    assert vistas_escritura == {s["org_a"], s["org_b"]}


# ── 4: run_db ──────────────────────────────────────────────────────────────


def test_run_db_acota_la_transaccion_que_abre_en_el_hilo(rol_runtime: str, tmp_db: Any) -> None:
    from api.concurrency import run_db

    db_mod, _ = tmp_db
    s = _sembrar(db_mod)

    def _leer() -> tuple[int | None, set[int | None]]:
        return current_organization(), set(_organizaciones_visibles(db_mod, "pursuits"))

    async def _main() -> tuple[int | None, set[int | None]]:
        with tenant_scope(s["org_a"]):
            return await run_db(_leer)

    ambito_en_hilo, vistas = anyio.run(_main)
    assert ambito_en_hilo == s["org_a"]
    assert vistas == {s["org_a"]}


# ── 5: ruta que pasa por api/tenancy.py ────────────────────────────────────


def test_ruta_acotada_fija_el_ambito_y_no_filtra_otra_organizacion(
    client: Any, rol_runtime: str, tmp_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /watchlist/items`` usa ``require_organization()``: la petición queda acotada.

    Se elige esta ruta y no ``/pursuits`` porque la vertical de pursuits
    resuelve la organización dentro de ``services/pursuits.py`` (excepción
    documentada en ``test_organization_sql_isolation.py``) y por tanto no pasa
    por ``api/tenancy.py``.

    La organización activa es una **compartida**, distinta de la personal. Es
    el caso que hace visible la otra mitad del contrato: la ruta ejecuta
    ``claim_legacy_scope`` dentro de la petición, y ese backfill escribe en la
    organización personal, no en la activa — si corriera con ámbito, el
    ``WITH CHECK`` lo rechazaría y la petición fallaría con 500.
    """
    import db.connection as conn_mod
    from api.app import app
    from api.routes.dual_auth import require_any_auth
    from db.repositories.organizations import OrganizationRepository

    db_mod, _ = tmp_db
    s = _sembrar(db_mod)
    org_equipo = int(OrganizationRepository().create_organization("Equipo A", s["user_a"])["id"])
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_limite, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s)",
            (
                "LIC-RLS-S",
                "Expediente del equipo",
                "2026-11-01T10:00:00+00:00",
                "2026-09-01T00:00:00+00:00",
            ),
        )
        c.execute(
            "INSERT INTO watchlist_items (user_key, user_id, id_externo, organization_id, visibility) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("rls-a", s["user_a"], "LIC-RLS-S", org_equipo, "private"),
        )

    # Espía sobre el punto exacto donde la conexión consulta el ámbito: lo que
    # registre es lo que vio el hilo del pool al abrir cada transacción.
    ambitos: list[int | None] = []
    real = conn_mod.current_organization

    def _espia() -> int | None:
        valor = real()
        ambitos.append(valor)
        return valor

    monkeypatch.setattr(conn_mod, "current_organization", _espia)
    app.dependency_overrides[require_any_auth] = lambda: {
        "user_id": s["user_a"],
        "auth_method": "session",
        "user_key": "rls-a",
    }
    try:
        propia = client.get("/api/v1/watchlist/items", params={"organization_id": org_equipo})
        assert propia.status_code == 200, propia.text
        ids = {item["id_externo"] for item in propia.json()["items"]}
        assert ids == {"LIC-RLS-S"}

        ajena = client.get("/api/v1/watchlist/items", params={"organization_id": s["org_b"]})
        assert ajena.status_code == 403
    finally:
        app.dependency_overrides.pop(require_any_auth, None)

    assert org_equipo in ambitos
    assert s["org_b"] not in ambitos

    # El backfill de la petición adjudicó la fila legada a la organización
    # personal (distinta de la activa) sin que la RLS lo impidiera.
    with db_mod.connect_read() as c:
        legada = c.execute(
            "SELECT organization_id FROM watchlist_items WHERE user_key = 'rls-legacy'"
        ).fetchone()
    assert legada is not None and legada[0] == s["org_a"]


# ── 6: estructural ─────────────────────────────────────────────────────────


def test_toda_tabla_con_organization_id_tiene_decision_rls(tmp_db: Any) -> None:
    """Ninguna tabla con ``organization_id`` queda sin decidir: políticas o exclusión.

    Corre como superusuario: solo mira el catálogo. Que las políticas hagan
    lo que dicen lo prueban los tests de arriba con el rol sonda.
    """
    db_mod, _ = tmp_db
    corporativas: set[str] = _tablas_corporativas()
    excluidas = set(TABLAS_EXCLUIDAS)
    assert not corporativas & excluidas

    with db_mod.connect_read() as c:
        schema = str(c.execute("SELECT current_schema()").fetchone()[0])
        con_columna = {
            str(r[0])
            for r in c.execute(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = %s AND column_name = 'organization_id'",
                (schema,),
            ).fetchall()
        }
        forzadas = {
            str(r[0])
            for r in c.execute(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relkind = 'r' AND c.relforcerowsecurity",
                (schema,),
            ).fetchall()
        }
        politicas = {
            (str(r[0]), str(r[1]), str(r[2]))
            for r in c.execute(
                "SELECT tablename, policyname, permissive FROM pg_policies "
                "WHERE schemaname = %s "
                "AND (policyname LIKE 'tenant_scope_%%' OR policyname LIKE 'tenant_guard_%%')",
                (schema,),
            ).fetchall()
        }

    sin_decision = con_columna - corporativas - excluidas
    assert not sin_decision, (
        f"Tablas con organization_id sin decisión RLS: {sorted(sin_decision)}. "
        "O su migración añade FORCE ROW LEVEL SECURITY y las políticas "
        "tenant_scope_/tenant_guard_ (patrón de v128), o se declara en "
        "TABLAS_EXCLUIDAS con el motivo."
    )
    assert corporativas <= con_columna, sorted(corporativas - con_columna)
    assert excluidas <= con_columna, sorted(excluidas - con_columna)

    for tabla in sorted(corporativas):
        assert tabla in forzadas, f"{tabla}: falta FORCE ROW LEVEL SECURITY"
        assert (tabla, f"tenant_scope_{tabla}", "PERMISSIVE") in politicas, tabla
        assert (tabla, f"tenant_guard_{tabla}", "RESTRICTIVE") in politicas, tabla
    for tabla in sorted(excluidas):
        assert tabla not in forzadas, f"{tabla}: excluida pero con FORCE"
        assert not {p for p in politicas if p[0] == tabla}, f"{tabla}: excluida pero con política"
