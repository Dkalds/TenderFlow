"""Colas de revisión humana del dato: duplicados (ADR-026) y órganos (ADR-032 §C).

Las dos colas se llenaban solas —el detector de duplicados marca ``pending``
lo que no puede confirmar, el resolver de órganos encola las fusiones dudosas—
y ninguna tenía quién las vaciara: la de duplicados solo se resolvía desde un
test, y la de órganos no tenía ni función. Aquí se fija el repositorio y la
regla de negocio que usa ``api/routes/admin_revision.py``.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _licitacion(c: Any, id_externo: str, *, organo: str, fuente: str = "placsp") -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, "
        " fecha_publicacion, fuente, fecha_extraccion) "
        "VALUES (%s, %s, %s, '72000000', '2026-05-01', %s, '2026-05-02T00:00:00')",
        (id_externo, f"Contrato {id_externo}", organo, fuente),
    )


def _par_pendiente(c: Any, duplicada: str, canonica: str) -> None:
    c.execute(
        "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
        " confianza, status) VALUES (%s, %s, 'organo|7200|2026-05|titulo', 0.8, 'pending')",
        (duplicada, canonica),
    )


# ---------------------------------------------------------------------------
# Duplicados: el SQL bajó de services/dedupe.py a db/repositories/dedupe.py
# ---------------------------------------------------------------------------


def test_pendientes_de_revision_trae_las_dos_filas_del_par(db) -> None:
    from db.database import connect
    from db.repositories import dedupe as repo

    with connect() as c:
        _licitacion(c, "EXP-1", organo="Ajuntament de Girona")
        _licitacion(c, "pscp:EXP-1", organo="Ajuntament de Girona", fuente="pscp")
        _par_pendiente(c, "pscp:EXP-1", "EXP-1")

    filas = repo.pendientes_de_revision()

    assert len(filas) == 1
    fila = filas[0]
    assert fila["licitacion_id"] == "pscp:EXP-1"
    assert fila["canonical_id"] == "EXP-1"
    assert fila["fuente"] == "pscp" and fila["fuente_canonica"] == "placsp"
    assert fila["titulo_canonica"] == "Contrato EXP-1"
    assert fila["confianza"] == pytest.approx(0.8)
    assert repo.pendientes_count() == 1


def test_resolver_pendiente_solo_toca_lo_pendiente(db) -> None:
    from db.database import connect, connect_read
    from db.repositories import dedupe as repo

    with connect() as c:
        _licitacion(c, "EXP-2", organo="Org")
        _licitacion(c, "pscp:EXP-2", organo="Org", fuente="pscp")
        _par_pendiente(c, "pscp:EXP-2", "EXP-2")

    assert repo.resolver_pendiente("pscp:EXP-2", accept=False, resolved_by="revisora")
    # Ya resuelto: una segunda decisión no lo reabre ni lo cambia.
    assert not repo.resolver_pendiente("pscp:EXP-2", accept=True, resolved_by="otro")
    assert not repo.resolver_pendiente("no-existe", accept=True)

    with connect_read() as c:
        fila = c.execute(
            "SELECT status, resolved_by, resolved_at FROM licitaciones_duplicados "
            "WHERE licitacion_id = 'pscp:EXP-2'"
        ).fetchone()
    assert fila[0] == "rejected" and fila[1] == "revisora"
    # TEXT ISO con `T` (v151): el formato que escriben el resto de caminos.
    assert "T" in str(fila[2])
    assert repo.pendientes_de_revision() == []
    assert repo.pendientes_count() == 0


# ---------------------------------------------------------------------------
# Órganos: resolver la cola (no existía ninguna función que lo hiciera)
# ---------------------------------------------------------------------------


def _organo_y_revision(nombre_dudoso: str) -> tuple[int, int]:
    """Un órgano en el maestro y una grafía parecida en la cola, como deja `resolver`."""
    from db.database import connect
    from db.repositories import organos as repo

    organo_id = repo.crear(
        nombre_canonico="Ayuntamiento de Villanueva del Pardillo",
        nombre_normalizado="ayuntamiento de villanueva del pardillo",
    )
    repo.encolar_revision(
        nombre_original=nombre_dudoso,
        alias_normalizado="ayuntamiento villanueva del pardillo",
        candidato_organo_id=organo_id,
        score=0.9,
    )
    with connect() as c:
        revision_id = int(
            c.execute("SELECT id FROM organo_review_queue WHERE status = 'pending'").fetchone()[0]
        )
    return organo_id, revision_id


def test_listar_pendientes_trae_el_nombre_del_candidato(db) -> None:
    from db.repositories import organos as repo

    organo_id, revision_id = _organo_y_revision("Ayto. Villanueva del Pardillo")

    filas = repo.listar_pendientes(limit=10)

    assert [f["id"] for f in filas] == [revision_id]
    assert filas[0]["candidato_organo_id"] == organo_id
    assert filas[0]["candidato_nombre"] == "Ayuntamiento de Villanueva del Pardillo"


def test_resolver_revision_reclama_la_fila_una_sola_vez(db) -> None:
    from db.repositories import organos as repo

    _organo_y_revision("  Ayto. Villanueva del Pardillo ")
    revision_id = repo.listar_pendientes(limit=1)[0]["id"]

    fila = repo.resolver_revision(revision_id, status="accepted", resolved_by="admin")

    assert fila is not None
    # `lower(btrim(...))`: el mismo predicado con el que `asignar_a_licitaciones`
    # busca la grafía cruda en `licitaciones`.
    assert fila["nombre_plano"] == "ayto. villanueva del pardillo"
    assert repo.resolver_revision(revision_id, status="rejected", resolved_by="otro") is None
    assert repo.revision_pendiente_count() == 0
    with pytest.raises(ValueError):
        repo.resolver_revision(revision_id, status="pending", resolved_by="x")


def test_aceptar_registra_el_alias_y_asigna_las_licitaciones(db) -> None:
    from db.database import connect, connect_read
    from db.repositories import organos as repo
    from services.organos import decidir_revision

    organo_id, revision_id = _organo_y_revision("Ayto. Villanueva del Pardillo")
    with connect() as c:
        _licitacion(c, "ORG-1", organo="Ayto. Villanueva del Pardillo")
        _licitacion(c, "ORG-2", organo=" AYTO. Villanueva del Pardillo")
        _licitacion(c, "ORG-3", organo="Otro órgano")

    decision = decidir_revision(revision_id, aceptar=True, resolved_by="admin", batch=1)

    assert decision is not None
    assert decision.organo_id == organo_id
    assert decision.organo_nuevo is False
    assert decision.filas_asignadas == 2
    # La próxima vez la grafía resuelve sola, sin volver a la cola.
    assert repo.get_by_nombre_normalizado("ayuntamiento villanueva del pardillo") is not None
    with connect_read() as c:
        asignadas = dict(
            c.execute(
                "SELECT id_externo, organo_id FROM licitaciones ORDER BY id_externo"
            ).fetchall()
        )
        estado = c.execute(
            "SELECT status, resolved_by FROM organo_review_queue WHERE id = %s", (revision_id,)
        ).fetchone()
    assert asignadas == {"ORG-1": organo_id, "ORG-2": organo_id, "ORG-3": None}
    assert tuple(estado) == ("accepted", "admin")
    # Ya no está pendiente: decidir otra vez no hace nada.
    assert decidir_revision(revision_id, aceptar=False, resolved_by="admin") is None


def test_rechazar_crea_un_organo_propio_y_lo_asigna(db) -> None:
    from db.database import connect, connect_read
    from services.organos import decidir_revision

    organo_id, revision_id = _organo_y_revision("Ayto. Villanueva del Pardillo")
    with connect() as c:
        _licitacion(c, "ORG-4", organo="Ayto. Villanueva del Pardillo")

    decision = decidir_revision(revision_id, aceptar=False, resolved_by="admin")

    assert decision is not None
    assert decision.organo_nuevo is True
    assert decision.organo_id != organo_id
    assert decision.filas_asignadas == 1
    with connect_read() as c:
        nuevo = c.execute(
            "SELECT nombre_canonico, nombre_normalizado FROM organos WHERE organo_id = %s",
            (decision.organo_id,),
        ).fetchone()
        estado = c.execute(
            "SELECT status FROM organo_review_queue WHERE id = %s", (revision_id,)
        ).fetchone()[0]
        asignado = c.execute(
            "SELECT organo_id FROM licitaciones WHERE id_externo = 'ORG-4'"
        ).fetchone()[0]
    assert tuple(nuevo) == ("Ayto. Villanueva del Pardillo", "ayuntamiento villanueva del pardillo")
    assert estado == "rejected"
    assert asignado == decision.organo_id


# ---------------------------------------------------------------------------
# Panel de calidad
# ---------------------------------------------------------------------------


def test_quality_publica_los_duplicados_pendientes(db) -> None:
    from db.database import connect
    from services.analytics.quality import get_quality

    assert get_quality().duplicados_pendientes == 0
    with connect() as c:
        _licitacion(c, "EXP-3", organo="Org")
        _licitacion(c, "pscp:EXP-3", organo="Org", fuente="pscp")
        _par_pendiente(c, "pscp:EXP-3", "EXP-3")

    assert get_quality().duplicados_pendientes == 1
