"""Reproceso dirigido del lote de las adjudicaciones ya guardadas.

Las adjudicaciones de expedientes multilote se guardaron sin ``lote_id`` hasta
2026-10 (el parser leía el lote en un sitio donde CODICE no lo publica). Este
reproceso lee los ZIP y lo asigna **en sitio**: la fila conserva su id y su
``empresa_id``, una asignación ambigua no se aplica y repetir no cambia nada.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from db.repositories.reproceso_lotes import AsignacionLote, asignar_lotes, multilote_sin_lote
from scraper import reproceso_lotes
from scraper.reproceso_lotes import asignaciones_de_entry, meses_entre, reprocesar

_FIXTURE = Path(__file__).parent / "fixtures" / "placsp" / "18_lote_en_proyecto_adjudicado.xml"
_LIC = "2026-MULTILOTE-0018"


def _entry() -> Any:
    return etree.fromstring(_FIXTURE.read_bytes())


# ─── Sin base de datos ───────────────────────────────────────────────────────


def test_meses_entre_cruza_el_cambio_de_año() -> None:
    assert meses_entre("2025-11", "2026-02") == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]


@pytest.mark.parametrize("malo", ["2025-13", "2025-1", "25-01", ""])
def test_meses_entre_rechaza_un_mes_mal_escrito(malo: str) -> None:
    with pytest.raises(ValueError):
        meses_entre(malo, "2026-01")


def test_meses_entre_rechaza_un_rango_al_reves() -> None:
    with pytest.raises(ValueError):
        meses_entre("2026-02", "2026-01")


def test_saca_las_adjudicaciones_con_lote_de_un_expediente_objetivo() -> None:
    asignaciones = asignaciones_de_entry(_entry(), {_LIC})

    # El tercer resultado del fixture no dice lote: no hay nada que asignar.
    assert [(a.nif, a.importe_adjudicado, a.lote_numero) for a in asignaciones] == [
        ("A28000001", 398000.0, "1"),
        ("B28000002", 295500.0, "2"),
    ]


def test_ignora_la_entry_de_un_expediente_que_no_es_objetivo() -> None:
    assert asignaciones_de_entry(_entry(), {"OTRO"}) == []


# ─── Contra Postgres ─────────────────────────────────────────────────────────


def _sembrar(
    conn: Any, licitacion_id: str, adjudicaciones: list[tuple[str, str | None, float]]
) -> None:
    conn.execute(
        "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) VALUES (%s, %s, %s)",
        (licitacion_id, "Expediente multilote", "2026-09-01T10:00:00+00:00"),
    )
    for numero in ("1", "2"):
        conn.execute(
            "INSERT INTO lotes (licitacion_id, numero, fecha_extraccion) VALUES (%s, %s, %s)",
            (licitacion_id, numero, "2026-09-01T10:00:00+00:00"),
        )
    for nombre, nif, importe in adjudicaciones:
        conn.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, nif, importe_adjudicado, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, %s)",
            (licitacion_id, nombre, nif, importe, "2026-09-01T10:00:00+00:00"),
        )


def _lotes_de(licitacion_id: str) -> dict[str, str | None]:
    """``{nombre: numero de su lote}``."""
    from db.database import connect

    with connect() as conn:
        rows = conn.execute(
            "SELECT a.nombre, lo.numero FROM adjudicaciones a "
            "LEFT JOIN lotes lo ON lo.id = a.lote_id WHERE a.licitacion_id = %s",
            (licitacion_id,),
        ).fetchall()
    return {str(r[0]): (str(r[1]) if r[1] is not None else None) for r in rows}


@pytest.fixture()
def multilote(tmp_db: Any) -> Iterator[None]:
    from db.database import connect

    with connect() as conn:
        _sembrar(
            conn,
            _LIC,
            [
                ("Integradora Iberica SA", "A28000001", 398000.0),
                ("Consultoria Digital SL", "B28000002", 295500.0),
                ("Sin NIF SL", None, 1000.0),
            ],
        )
    yield


def test_objetivo_son_los_multilote_con_adjudicaciones_sin_lote(multilote: None) -> None:
    assert multilote_sin_lote() == {_LIC}


def test_asigna_el_lote_en_sitio_por_nif_e_importe(multilote: None) -> None:
    cambiadas = asignar_lotes(
        [
            AsignacionLote(_LIC, "Integradora Iberica SA", "A28000001", 398000.0, "1"),
            AsignacionLote(_LIC, "Consultoria Digital SL", "B28000002", 295500.0, "2"),
            AsignacionLote(_LIC, "Sin NIF SL", None, 1000.0, "2"),
        ]
    )

    assert cambiadas == 3
    assert _lotes_de(_LIC) == {
        "Integradora Iberica SA": "1",
        "Consultoria Digital SL": "2",
        "Sin NIF SL": "2",
    }
    assert multilote_sin_lote() == set()


def test_no_aplica_una_asignacion_ambigua(multilote: None) -> None:
    """La misma empresa por el mismo importe en dos lotes: no se sabe cuál."""
    cambiadas = asignar_lotes(
        [
            AsignacionLote(_LIC, "Integradora Iberica SA", "A28000001", 398000.0, "1"),
            AsignacionLote(_LIC, "Integradora Iberica SA", "A28000001", 398000.0, "2"),
        ]
    )

    assert cambiadas == 0
    assert _lotes_de(_LIC)["Integradora Iberica SA"] is None


def test_una_fila_que_no_casa_se_queda_como_estaba(multilote: None) -> None:
    assert asignar_lotes([AsignacionLote(_LIC, "Otra", "Z99999999", 5.0, "1")]) == 0
    assert set(_lotes_de(_LIC).values()) == {None}


def test_reprocesar_lee_el_mes_y_asigna(multilote: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reproceso_lotes, "_entries_del_mes", lambda year, month: iter([_entry()]))

    contado = reprocesar("2026-06", "2026-06", aplicar=False)
    assert (contado.asignaciones, contado.filas_actualizadas) == (2, 0)
    assert set(_lotes_de(_LIC).values()) == {None}

    aplicado = reprocesar("2026-06", "2026-06", aplicar=True)
    assert aplicado.filas_actualizadas == 2
    assert _lotes_de(_LIC)["Consultoria Digital SL"] == "2"

    # Repetir no cambia nada: solo se rellena el `lote_id` vacío.
    assert reprocesar("2026-06", "2026-06", aplicar=True).filas_actualizadas == 0


def test_casa_el_importe_que_la_columna_real_redondeo(tmp_db: Any) -> None:
    """La forma que dejaba sin lote a las adjudicaciones con céntimos.

    En producción ``importe_adjudicado`` fue ``real`` hasta ``v155``: 39.567,94 €
    quedó guardado como 39.567,94140625, y migrar la columna a float8 no
    devuelve los céntimos. El XML trae 39.567,94, y la igualdad exacta contra el
    float8 del parser no casaba nunca: medido el 2026-10-23, 113 de las 121
    adjudicaciones de expedientes multilote que seguían sin lote tenían un
    importe así. Se compara a la precisión de ``real``, que cubre las filas
    viejas y las que ya se escriban en float8.
    """
    from db.database import connect

    fecha = "2026-09-01T10:00:00+00:00"
    with connect() as conn:
        _sembrar(conn, _LIC, [])
        conn.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, nif, importe_adjudicado, fecha_extraccion) "
            "VALUES (%s, 'Redondeada SL', 'B28000003', %s::real, %s), "
            "       (%s, 'Exacta SL', 'B28000004', %s, %s)",
            (_LIC, 39567.94, fecha, _LIC, 24415.51, fecha),
        )

    cambiadas = asignar_lotes(
        [
            AsignacionLote(_LIC, "Redondeada SL", "B28000003", 39567.94, "1"),
            AsignacionLote(_LIC, "Exacta SL", "B28000004", 24415.51, "2"),
        ]
    )

    assert cambiadas == 2
    assert _lotes_de(_LIC) == {"Redondeada SL": "1", "Exacta SL": "2"}
