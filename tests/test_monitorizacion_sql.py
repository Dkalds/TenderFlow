"""SQL de los monitores del scheduler contra Postgres (``db/monitorizacion.py``).

Las reglas (umbrales, KS, TF-IDF) tienen sus tests con las lecturas
parcheadas; estos fijan que cada lectura filtra lo que su docstring dice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def _dia(delta_dias: int) -> str:
    return (datetime.now(UTC) + timedelta(days=delta_dias)).strftime("%Y-%m-%d %H:%M:%S")


def _sembrar_licitaciones(filas: list[tuple[object, ...]]) -> None:
    from db.database import connect

    with connect() as c:
        for id_externo, organo, importe, fecha, ml_proba, motivo in filas:
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, descripcion, organo_contratacion, "
                "importe, fecha_publicacion, ml_proba, inclusion_reason, fecha_extraccion) "
                "VALUES (%s, %s, 'desc', %s, %s, %s, %s, %s, %s)",
                (
                    id_externo,
                    f"titulo {id_externo}",
                    organo,
                    importe,
                    fecha,
                    ml_proba,
                    motivo,
                    _dia(0),
                ),
            )


def test_importes_del_organo_filtra_organo_ventana_y_nulos(tmp_db):
    from db.monitorizacion import importes_del_organo

    _sembrar_licitaciones(
        [
            ("A", "Ayto", 100.0, _dia(-10), None, None),
            ("B", "Ayto", None, _dia(-10), None, None),
            ("C", "Ayto", 300.0, _dia(-500), None, None),
            ("D", "Otro", 400.0, _dia(-10), None, None),
        ]
    )

    assert importes_del_organo("Ayto", 12) == [100.0]


def test_publicadas_y_licitaciones_ultimas_24h_cuentan_solo_lo_reciente(tmp_db):
    from db.monitorizacion import licitaciones_ultimas_24h, publicadas_en_los_ultimos_dias

    _sembrar_licitaciones(
        [
            ("HOY", "Ayto", 1.0, _dia(0), None, None),
            ("SEMANA", "Ayto", 1.0, _dia(-7), None, None),
            ("VIEJA", "Ayto", 1.0, _dia(-60), None, None),
        ]
    )

    assert publicadas_en_los_ultimos_dias(30) == 2
    assert publicadas_en_los_ultimos_dias(1) == 1
    assert [f["id_externo"] for f in licitaciones_ultimas_24h()] == ["HOY"]


def test_adjudicaciones_ultimas_24h_trae_el_importe_de_la_licitacion(tmp_db):
    from db.database import connect
    from db.monitorizacion import adjudicaciones_ultimas_24h

    _sembrar_licitaciones(
        [
            ("L1", "Ayto", 1000.0, _dia(-20), None, None),
            ("L2", "Ayto", 0.0, _dia(-20), None, None),
        ]
    )
    with connect() as c:
        for lic, fecha in (("L1", _dia(0)[:10]), ("L1", _dia(-30)[:10]), ("L2", _dia(0)[:10])):
            c.execute(
                "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
                "fecha_adjudicacion, fecha_extraccion) VALUES (%s, 'Empresa', 500.0, %s, %s)",
                (lic, fecha, _dia(0)),
            )

    filas = adjudicaciones_ultimas_24h()

    assert [(f["licitacion_id"], f["importe_licitacion"]) for f in filas] == [("L1", 1000.0)]


def test_textos_recientes_excluye_el_universo_cpv_sin_senal(tmp_db):
    from db.monitorizacion import textos_recientes

    _sembrar_licitaciones(
        [
            ("SI", "Ayto", 1.0, _dia(-1), None, "keyword"),
            ("NULO", "Ayto", 1.0, _dia(-1), None, None),
            ("UNIVERSO", "Ayto", 1.0, _dia(-1), None, "cpv_ti_universe"),
            ("VIEJA", "Ayto", 1.0, _dia(-90), None, "keyword"),
        ]
    )

    titulos = sorted(t for t, _ in textos_recientes(_dia(-30)))

    assert titulos == ["titulo NULO", "titulo SI"]


def test_ml_proba_por_ventana_separa_las_dos_ventanas(tmp_db):
    from db.monitorizacion import ml_proba_por_ventana

    _sembrar_licitaciones(
        [
            ("R", "Ayto", 1.0, _dia(-3), 0.9, None),
            ("P", "Ayto", 1.0, _dia(-20), 0.2, None),
            ("SIN", "Ayto", 1.0, _dia(-3), None, None),
            ("FUERA", "Ayto", 1.0, _dia(-60), 0.5, None),
        ]
    )

    assert ml_proba_por_ventana(_dia(-14), _dia(-28)) == ([0.9], [0.2])


def test_revision_ti_desde_trae_la_ultima_revision_por_expediente(tmp_db):
    from db.database import connect
    from db.repositories.feedback import FUENTE_REVISION_TI, FeedbackRepository

    _sembrar_licitaciones([("E1", "Ayto", 10.0, _dia(-5), None, None)])
    with connect() as c:
        for relevante, fuente, creado in (
            (1, FUENTE_REVISION_TI, _dia(-3)),
            (0, FUENTE_REVISION_TI, _dia(-1)),
            (1, "llm_batch", _dia(0)),
        ):
            c.execute(
                "INSERT INTO ml_feedback (expediente, relevante, nota, source, created_at) "
                "VALUES ('E1', %s, '', %s, %s)",
                (relevante, fuente, creado),
            )

    filas = FeedbackRepository().revision_ti_desde(_dia(-7))

    assert [(f[0], f[1], f[5]) for f in filas] == [("E1", 0, 10.0)]
